"""Create, verify, and safely restore local TAK AUTO trend-factory backups."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import sys
import tempfile
from typing import Any
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


MANIFEST_NAME = "tak-auto-backup-manifest.json"
FORMAT_VERSION = 1
# The authenticated header binds the format and PBKDF2 work factor to each archive.
ENCRYPTED_MAGIC = b"TAKENC01"
KDF_ITERATIONS = 1_200_000
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
ENCRYPTED_HEADER_BYTES = len(ENCRYPTED_MAGIC) + 4 + SALT_BYTES + NONCE_BYTES
IO_CHUNK_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class BackupError(ValueError):
    """Backup cannot be created, verified, or restored safely."""


def _rename_directory_without_replacing(source: Path, destination: Path) -> None:
    """Atomically publish a restore directory only if its target is still absent."""
    if os.name == "nt":
        # Windows rename refuses to replace any existing destination.
        os.rename(source, destination)
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise BackupError("이 Linux 환경은 대상 덮어쓰기 없는 원자적 복구를 지원하지 않습니다.")
        renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), str(destination))
        raise OSError(error_number, os.strerror(error_number), str(destination))
    raise BackupError("이 운영체제는 대상 덮어쓰기 없는 원자적 복구를 지원하지 않습니다.")


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BackupError("백업 파일 경로가 올바르지 않습니다.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError("백업 파일 경로가 올바르지 않습니다.")
    normalized = path.as_posix()
    if normalized != value or normalized == MANIFEST_NAME:
        raise BackupError("백업 파일 경로가 올바르지 않습니다.")
    return normalized


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def is_encrypted_backup(archive_path: str | Path) -> bool:
    """Return whether an archive starts with this tool's encrypted format marker."""
    try:
        with Path(archive_path).open("rb") as source:
            return source.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC
    except OSError:
        return False


def _validate_passphrase(passphrase: str) -> None:
    if not isinstance(passphrase, str) or len(passphrase) < 16:
        raise BackupError("백업 암호문구는 16자 이상이어야 합니다.")


def _derive_backup_key(passphrase: str, salt: bytes) -> bytes:
    _validate_passphrase(passphrase)
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    ).derive(passphrase.encode("utf-8"))


class _GCMEncryptingWriter:
    """Non-seekable writer that encrypts ZIP output as it is written."""

    def __init__(self, target: Any, encryptor: Any) -> None:
        self._target = target
        self._encryptor = encryptor
        self._position = 0

    def write(self, data: bytes) -> int:
        encrypted = self._encryptor.update(data)
        written = self._target.write(encrypted)
        if written != len(encrypted):
            raise OSError("암호화 백업을 끝까지 쓰지 못했습니다.")
        self._position += len(data)
        return len(data)

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:
        self._target.flush()

    def finish(self) -> None:
        self._target.write(self._encryptor.finalize())
        self._target.write(self._encryptor.tag)


def _write_encrypted_zip(
    files: list[tuple[str, Path]],
    manifest: dict[str, Any],
    encrypted_path: str | Path,
    passphrase: str,
) -> None:
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    header = ENCRYPTED_MAGIC + struct.pack(">I", KDF_ITERATIONS) + salt + nonce
    key = _derive_backup_key(passphrase, salt)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    with Path(encrypted_path).open("wb") as target:
        target.write(header)
        encrypted_writer = _GCMEncryptingWriter(target, encryptor)
        with zipfile.ZipFile(
            encrypted_writer, "w", compression=zipfile.ZIP_DEFLATED
        ) as bundle:
            for relative, path in files:
                info = zipfile.ZipInfo(relative)
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                with path.open("rb") as source_file, bundle.open(info, "w") as zip_entry:
                    shutil.copyfileobj(source_file, zip_entry)
            bundle.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        encrypted_writer.finish()
        target.flush()
        if os.name == "posix":
            os.fsync(target.fileno())
            os.chmod(encrypted_path, 0o600)


@contextmanager
def _decrypted_archive_path(archive_path: str | Path, passphrase: str | None):
    """Yield a verified private temporary ZIP for encrypted archives.

    GCM decryption emits unauthenticated bytes before finalization. They are
    written only to a mode-0600 temporary file and are never opened as a ZIP
    until the final authentication tag has been checked.
    """
    archive = Path(archive_path)
    if not is_encrypted_backup(archive):
        yield archive
        return
    if passphrase is None:
        raise BackupError("이 백업은 암호화되어 있습니다. 암호문구를 입력해야 합니다.")

    temporary_name: str | None = None
    try:
        with archive.open("rb") as source:
            header = source.read(ENCRYPTED_HEADER_BYTES)
            if len(header) != ENCRYPTED_HEADER_BYTES or not header.startswith(ENCRYPTED_MAGIC):
                raise BackupError("암호화 백업 헤더가 손상되었습니다.")
            iterations_end = len(ENCRYPTED_MAGIC) + 4
            iterations = struct.unpack(">I", header[len(ENCRYPTED_MAGIC):iterations_end])[0]
            if iterations != KDF_ITERATIONS:
                raise BackupError("지원하지 않는 암호화 백업 형식입니다.")
            salt_start = len(ENCRYPTED_MAGIC) + 4
            salt = header[salt_start:salt_start + SALT_BYTES]
            nonce = header[salt_start + SALT_BYTES:]
            key = _derive_backup_key(passphrase, salt)
            decryptor = Cipher(
                algorithms.AES(key), modes.GCM(nonce, min_tag_length=TAG_BYTES),
            ).decryptor()
            decryptor.authenticate_additional_data(header)
            with tempfile.NamedTemporaryFile(
                prefix="tak-auto-decrypted-backup-", suffix=".zip", delete=False,
            ) as temporary:
                temporary_name = temporary.name
                if os.name == "posix":
                    os.chmod(temporary_name, 0o600)
                tail = b""
                while chunk := source.read(IO_CHUNK_BYTES):
                    buffered = tail + chunk
                    if len(buffered) > TAG_BYTES:
                        ciphertext, tail = buffered[:-TAG_BYTES], buffered[-TAG_BYTES:]
                        temporary.write(decryptor.update(ciphertext))
                    else:
                        tail = buffered
                if len(tail) != TAG_BYTES:
                    raise BackupError("암호화 백업 데이터가 잘렸습니다.")
                try:
                    temporary.write(decryptor.finalize_with_tag(tail))
                except InvalidTag:
                    raise BackupError("암호문구가 틀렸거나 암호화 백업이 변조되었습니다.") from None
                temporary.flush()
                if os.name == "posix":
                    os.fsync(temporary.fileno())
        yield Path(temporary_name)
    except InvalidTag:
        raise BackupError("암호문구가 틀렸거나 암호화 백업이 변조되었습니다.") from None
    except OSError as error:
        raise BackupError(f"암호화 백업을 읽지 못했습니다: {error}") from None
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def create_backup(
    source_dir: str | Path,
    archive_path: str | Path,
    *,
    passphrase: str | None = None,
) -> dict[str, Any]:
    """Create a private, atomic ZIP snapshot, optionally encrypting the archive."""
    if passphrase is not None:
        _validate_passphrase(passphrase)
    source = Path(source_dir).expanduser().resolve()
    archive = Path(archive_path).expanduser().absolute()
    if not source.is_dir():
        raise BackupError("백업할 데이터 디렉터리가 없습니다.")
    try:
        archive.resolve().relative_to(source)
    except ValueError:
        pass
    else:
        raise BackupError("백업 파일은 원본 데이터 디렉터리 밖에 저장해야 합니다.")
    if archive.exists():
        raise BackupError("백업 파일이 이미 있습니다. 덮어쓰지 않습니다.")
    archive.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    files: list[tuple[str, Path]] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise BackupError(f"심볼릭 링크는 백업할 수 없습니다: {path.relative_to(source)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise BackupError(f"일반 파일이 아닌 항목은 백업할 수 없습니다: {path.relative_to(source)}")
        relative = _safe_relative_path(path.relative_to(source).as_posix())
        if relative == MANIFEST_NAME:
            raise BackupError(f"예약된 백업 파일명이 데이터에 있습니다: {MANIFEST_NAME}")
        size, sha256 = _file_digest(path)
        entries.append({"path": relative, "size": size, "sha256": sha256})
        files.append((relative, path))

    manifest = {"format_version": FORMAT_VERSION, "files": entries}
    encrypted_temporary_name: str | None = None
    zip_temporary_name: str | None = None
    try:
        if passphrase is not None:
            with tempfile.NamedTemporaryFile(
                prefix=f".{archive.name}.", suffix=".encrypted.tmp", dir=archive.parent, delete=False,
            ) as temporary:
                encrypted_temporary_name = temporary.name
            candidate_name = encrypted_temporary_name
            _write_encrypted_zip(files, manifest, candidate_name, passphrase)
            # Confirm the stream is a complete authenticated ZIP and detect files
            # that changed between manifest collection and archive writing.
            verify_backup(candidate_name, passphrase=passphrase)
        else:
            with tempfile.NamedTemporaryFile(
                prefix=f".{archive.name}.", suffix=".zip.tmp", dir=archive.parent, delete=False,
            ) as temporary:
                zip_temporary_name = temporary.name
                if os.name == "posix":
                    os.chmod(zip_temporary_name, 0o600)
            with zipfile.ZipFile(zip_temporary_name, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for relative, path in files:
                    info = zipfile.ZipInfo(relative)
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    with path.open("rb") as source_file, bundle.open(info, "w") as target:
                        shutil.copyfileobj(source_file, target)
                bundle.writestr(
                    MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                )
            _verify_zip_archive(zip_temporary_name)
            candidate_name = zip_temporary_name
        expected_paths = [entry["path"] for entry in entries]
        current_paths = []
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise BackupError(f"백업 중 원본에 심볼릭 링크가 생겼습니다: {path.relative_to(source)}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise BackupError(f"백업 중 원본에 일반 파일이 아닌 항목이 생겼습니다: {path.relative_to(source)}")
            current_paths.append(_safe_relative_path(path.relative_to(source).as_posix()))
        if current_paths != expected_paths:
            raise BackupError("백업 중 원본 파일 목록이 변경되었습니다. 데이터 쓰기를 멈춘 뒤 다시 시도하세요.")
        if os.name == "posix":
            with open(candidate_name, "rb+") as handle:
                os.fsync(handle.fileno())
            os.chmod(candidate_name, 0o600)
        # Hard-link gives create-only semantics even if another writer races us.
        os.link(candidate_name, archive)
    except FileExistsError:
        raise BackupError("백업 파일이 이미 있습니다. 덮어쓰지 않습니다.") from None
    except OSError as error:
        raise BackupError(f"백업 파일을 만들지 못했습니다: {error}") from None
    finally:
        for temporary_name in (encrypted_temporary_name, zip_temporary_name):
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
    return manifest


def _verify_zip_archive(archive_path: str | Path) -> dict[str, Any]:
    """Validate archive structure, every file size, and every SHA-256 digest."""
    try:
        with zipfile.ZipFile(archive_path, "r") as bundle:
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or names.count(MANIFEST_NAME) != 1:
                raise BackupError("백업 안의 파일 구성이 중복되었거나 manifest가 없습니다.")
            for info in infos:
                if info.filename == MANIFEST_NAME:
                    continue
                _safe_relative_path(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                    raise BackupError("백업에 일반 파일이 아닌 항목이 있습니다.")
            manifest_info = bundle.getinfo(MANIFEST_NAME)
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise BackupError("백업 manifest가 허용 크기를 초과합니다.")
            with bundle.open(MANIFEST_NAME) as manifest_file:
                manifest_bytes = manifest_file.read(MAX_MANIFEST_BYTES + 1)
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise BackupError("백업 manifest가 허용 크기를 초과합니다.")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("format_version") != FORMAT_VERSION:
                raise BackupError("지원하지 않는 백업 형식입니다.")
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise BackupError("백업 manifest의 파일 목록이 올바르지 않습니다.")
            expected: dict[str, dict[str, Any]] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    raise BackupError("백업 manifest 항목이 올바르지 않습니다.")
                relative = _safe_relative_path(entry.get("path"))
                size, digest = entry.get("size"), entry.get("sha256")
                if relative in expected or type(size) is not int or size < 0:
                    raise BackupError("백업 manifest 항목이 중복되었거나 크기가 올바르지 않습니다.")
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise BackupError("백업 manifest의 SHA-256 값이 올바르지 않습니다.")
                expected[relative] = entry
            if set(names) != set(expected) | {MANIFEST_NAME}:
                raise BackupError("백업 파일과 manifest의 목록이 일치하지 않습니다.")
            for relative, entry in expected.items():
                digest = hashlib.sha256()
                size = 0
                with bundle.open(relative) as source:
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > entry["size"]:
                            raise BackupError(
                                f"백업 파일 크기가 manifest 선언을 초과합니다: {relative}"
                            )
                        digest.update(chunk)
                if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                    raise BackupError(f"백업 파일 검증에 실패했습니다: {relative}")
            return manifest
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
        raise BackupError(f"백업 파일을 읽거나 검증하지 못했습니다: {error}") from None


def verify_backup(
    archive_path: str | Path,
    *,
    passphrase: str | None = None,
) -> dict[str, Any]:
    """Validate a plaintext or encrypted archive without extracting its files."""
    with _decrypted_archive_path(archive_path, passphrase) as zip_path:
        return _verify_zip_archive(zip_path)


def restore_backup(
    archive_path: str | Path,
    destination_dir: str | Path,
    *,
    passphrase: str | None = None,
) -> dict[str, Any]:
    """Restore a verified backup into a new directory without replacing data."""
    archive = Path(archive_path).expanduser()
    destination = Path(destination_dir).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise BackupError("복구 대상 경로가 이미 있습니다. 기존 데이터를 덮어쓰지 않습니다.")
    with _decrypted_archive_path(archive, passphrase) as zip_path:
        manifest = _verify_zip_archive(zip_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        required_bytes = sum(entry["size"] for entry in manifest["files"])
        try:
            available_bytes = shutil.disk_usage(destination.parent).free
        except OSError as error:
            raise BackupError(f"복구 대상 디스크의 여유 공간을 확인하지 못했습니다: {error}") from None
        if available_bytes < required_bytes:
            raise BackupError(
                "복구 대상 디스크의 여유 공간이 부족합니다 "
                f"(필요: {required_bytes}바이트, 남음: {available_bytes}바이트)."
            )
        stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent))
        try:
            with zipfile.ZipFile(zip_path, "r") as bundle:
                for entry in manifest["files"]:
                    relative = _safe_relative_path(entry["path"])
                    target = stage.joinpath(*PurePosixPath(relative).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(relative) as source, target.open("wb") as output:
                        restored_bytes = 0
                        while True:
                            # Re-check the manifest limit while extracting too:
                            # a plaintext archive may be replaced after preflight.
                            chunk = source.read(min(IO_CHUNK_BYTES, entry["size"] - restored_bytes + 1))
                            if not chunk:
                                break
                            restored_bytes += len(chunk)
                            if restored_bytes > entry["size"]:
                                raise BackupError(
                                    f"복구 파일 크기가 manifest 선언을 초과합니다: {relative}"
                                )
                            output.write(chunk)
                    size, digest = _file_digest(target)
                    if size != entry["size"] or digest != entry["sha256"]:
                        raise BackupError(f"복구 중 파일 검증에 실패했습니다: {relative}")
                    if os.name == "posix":
                        os.chmod(target, 0o600)
                if os.name == "posix":
                    for directory in sorted((p for p in stage.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                        os.chmod(directory, 0o700)
                    os.chmod(stage, 0o700)
            _rename_directory_without_replacing(stage, destination)
            return manifest
        except FileExistsError:
            raise BackupError("복구 대상 경로가 이미 있습니다. 기존 데이터를 덮어쓰지 않습니다.") from None
        except (OSError, zipfile.BadZipFile) as error:
            raise BackupError(f"백업 복구에 실패했습니다: {error}") from None
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
