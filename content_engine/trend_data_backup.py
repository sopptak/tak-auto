"""Create, verify, and safely restore local TAK AUTO trend-factory backups."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any
import zipfile


MANIFEST_NAME = "tak-auto-backup-manifest.json"
FORMAT_VERSION = 1


class BackupError(ValueError):
    """Backup cannot be created, verified, or restored safely."""


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


def create_backup(source_dir: str | Path, archive_path: str | Path) -> dict[str, Any]:
    """Create a private, atomic ZIP snapshot; never overwrite an existing archive."""
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
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{archive.name}.", suffix=".tmp", dir=archive.parent, delete=False,
        ) as temporary:
            temporary_name = temporary.name
        with zipfile.ZipFile(temporary_name, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for relative, path in files:
                info = zipfile.ZipInfo(relative)
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                with path.open("rb") as source_file, bundle.open(info, "w") as target:
                    shutil.copyfileobj(source_file, target)
            bundle.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        # Detect files that changed between manifest collection and archive read.
        verify_backup(temporary_name)
        if os.name == "posix":
            with open(temporary_name, "rb+") as handle:
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
        # Hard-link gives create-only semantics even if another writer races us.
        os.link(temporary_name, archive)
        os.unlink(temporary_name)
        temporary_name = None
    except FileExistsError:
        raise BackupError("백업 파일이 이미 있습니다. 덮어쓰지 않습니다.") from None
    except OSError as error:
        raise BackupError(f"백업 파일을 만들지 못했습니다: {error}") from None
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return manifest


def verify_backup(archive_path: str | Path) -> dict[str, Any]:
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
            manifest = json.loads(bundle.read(MANIFEST_NAME).decode("utf-8"))
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
                        digest.update(chunk)
                if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                    raise BackupError(f"백업 파일 검증에 실패했습니다: {relative}")
            return manifest
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
        raise BackupError(f"백업 파일을 읽거나 검증하지 못했습니다: {error}") from None


def restore_backup(archive_path: str | Path, destination_dir: str | Path) -> dict[str, Any]:
    """Restore a verified backup into a new directory without replacing data."""
    manifest = verify_backup(archive_path)
    destination = Path(destination_dir).expanduser().absolute()
    if destination.exists():
        raise BackupError("복구 대상 경로가 이미 있습니다. 기존 데이터를 덮어쓰지 않습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path, "r") as bundle:
            for entry in manifest["files"]:
                relative = _safe_relative_path(entry["path"])
                target = stage.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(relative) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                size, digest = _file_digest(target)
                if size != entry["size"] or digest != entry["sha256"]:
                    raise BackupError(f"복구 중 파일 검증에 실패했습니다: {relative}")
                if os.name == "posix":
                    os.chmod(target, 0o600)
            if os.name == "posix":
                for directory in sorted((p for p in stage.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                    os.chmod(directory, 0o700)
                os.chmod(stage, 0o700)
        os.rename(stage, destination)
        return manifest
    except FileExistsError:
        raise BackupError("복구 대상 경로가 이미 있습니다. 기존 데이터를 덮어쓰지 않습니다.") from None
    except (OSError, zipfile.BadZipFile) as error:
        raise BackupError(f"백업 복구에 실패했습니다: {error}") from None
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
