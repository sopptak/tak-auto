"""Persistent, signed public media assets for approved video publishing.

Only MP4 files are accepted. Uploads live on the configured persistent data disk;
public reads require a time-limited HMAC URL so the dashboard itself stays private.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import BinaryIO
from urllib.parse import urlencode, urlsplit


ASSET_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
MAX_SIGNED_URL_TTL_SECONDS = 30 * 24 * 60 * 60
_INDEX_LOCK = threading.Lock()


class MediaAssetError(ValueError):
    """Invalid, missing, or inaccessible uploaded media asset."""


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    filename: str
    size_bytes: int
    created_at: str
    path: Path

    def to_public_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }


class MediaAssetStore:
    def __init__(self, data_dir: Path | str, signing_key: str, public_url: str = ""):
        self.data_dir = Path(data_dir)
        self.asset_dir = self.data_dir / "media_assets"
        self.index_path = self.data_dir / "tak_auto_media_assets.json"
        self.signing_key = signing_key.strip()
        self.public_url = public_url.strip().rstrip("/")
        if len(self.signing_key) < 32:
            raise MediaAssetError("TAK_AUTO_MEDIA_SIGNING_KEY는 32자 이상의 비밀값이어야 합니다.")

    def _load_index(self) -> list[dict[str, object]]:
        if not self.index_path.exists():
            return []
        try:
            rows = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise MediaAssetError("미디어 자산 목록을 읽을 수 없습니다.") from None
        if not isinstance(rows, list):
            raise MediaAssetError("미디어 자산 목록 형식이 올바르지 않습니다.")
        return [row for row in rows if isinstance(row, dict)]

    def _save_index(self, rows: list[dict[str, object]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.data_dir, delete=False) as handle:
                temporary_path = Path(handle.name)
                json.dump(rows, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary_path, 0o600)
            except OSError:
                pass
            os.replace(temporary_path, self.index_path)
            temporary_path = None
            try:
                directory_fd = os.open(self.data_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def list_assets(self) -> list[MediaAsset]:
        assets = []
        for row in self._load_index():
            asset_id = str(row.get("asset_id") or "")
            if not ASSET_ID_PATTERN.fullmatch(asset_id):
                continue
            path = self.asset_dir / f"{asset_id}.mp4"
            if not path.is_file():
                continue
            assets.append(MediaAsset(
                asset_id=asset_id,
                filename=str(row.get("filename") or "video.mp4"),
                size_bytes=int(row.get("size_bytes") or path.stat().st_size),
                created_at=str(row.get("created_at") or ""),
                path=path,
            ))
        return sorted(assets, key=lambda asset: asset.created_at, reverse=True)

    def get_asset(self, asset_id: str) -> MediaAsset:
        if not ASSET_ID_PATTERN.fullmatch(str(asset_id or "")):
            raise MediaAssetError("미디어 자산 ID 형식이 올바르지 않습니다.")
        for asset in self.list_assets():
            if asset.asset_id == asset_id:
                return asset
        raise MediaAssetError("미디어 자산을 찾을 수 없습니다.")

    def save_stream(self, stream: BinaryIO, content_length: int, filename: str,
                    *, max_bytes: int = DEFAULT_MAX_BYTES) -> MediaAsset:
        if content_length <= 0 or content_length > max_bytes:
            raise MediaAssetError(f"MP4 파일 크기는 1~{max_bytes // (1024 * 1024)}MB 범위여야 합니다.")
        safe_name = Path(str(filename or "video.mp4").replace("\\", "/")).name
        safe_name = "".join(char for char in safe_name if char.isprintable() and char not in "\r\n")[:160]
        if not safe_name.lower().endswith(".mp4"):
            raise MediaAssetError("MP4 파일만 등록할 수 있습니다.")
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        asset_id = os.urandom(16).hex()
        final_path = self.asset_dir / f"{asset_id}.mp4"
        written = 0
        header = b""
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=self.asset_dir, delete=False) as handle:
                temporary_path = Path(handle.name)
                while written < content_length:
                    chunk = stream.read(min(1024 * 1024, content_length - written))
                    if not chunk:
                        raise MediaAssetError("업로드된 파일 길이가 Content-Length와 일치하지 않습니다.")
                    if len(header) < 12:
                        header += chunk[:12 - len(header)]
                    handle.write(chunk)
                    written += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if len(header) < 12 or header[4:8] != b"ftyp":
                raise MediaAssetError("업로드 파일이 올바른 MP4 컨테이너가 아닙니다.")
            temporary_path.replace(final_path)
            try:
                directory_fd = os.open(self.asset_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
            created_at = datetime.now(timezone.utc).isoformat()
            row = {
                "asset_id": asset_id, "filename": safe_name,
                "size_bytes": written, "created_at": created_at,
            }
            with _INDEX_LOCK:
                rows = self._load_index()
                rows.append(row)
                self._save_index(rows)
            return MediaAsset(asset_id, safe_name, written, created_at, final_path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            raise

    def _signature(self, asset_id: str, expires_at: int) -> str:
        message = f"{asset_id}:{expires_at}".encode("ascii")
        return hmac.new(self.signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def signed_url(self, asset_id: str, *, ttl_seconds: int = 48 * 60 * 60,
                   now: int | None = None) -> str:
        self.get_asset(asset_id)
        if not self.public_url:
            raise MediaAssetError("TAK_AUTO_PUBLIC_URL이 설정되지 않았습니다.")
        parsed = urlsplit(self.public_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
            raise MediaAssetError("공개 미디어 URL에는 도메인만 포함된 HTTPS 주소가 필요합니다.")
        if ttl_seconds < 60 or ttl_seconds > MAX_SIGNED_URL_TTL_SECONDS:
            raise MediaAssetError("미디어 URL 유효기간은 1분~30일 범위여야 합니다.")
        issued = int(datetime.now(timezone.utc).timestamp()) if now is None else int(now)
        expires_at = issued + ttl_seconds
        signature = self._signature(asset_id, expires_at)
        query = urlencode({"expires": expires_at, "signature": signature})
        return f"{self.public_url}/media/assets/{asset_id}?{query}"

    def resolve_signed(self, asset_id: str, expires: str, signature: str,
                       *, now: int | None = None) -> MediaAsset:
        if not ASSET_ID_PATTERN.fullmatch(str(asset_id or "")):
            raise MediaAssetError("미디어 자산 ID 형식이 올바르지 않습니다.")
        try:
            expires_at = int(expires)
        except (TypeError, ValueError, OverflowError):
            raise MediaAssetError("미디어 URL 만료 정보가 올바르지 않습니다.") from None
        current = int(datetime.now(timezone.utc).timestamp()) if now is None else int(now)
        if expires_at <= current or expires_at > current + MAX_SIGNED_URL_TTL_SECONDS:
            raise MediaAssetError("미디어 URL이 만료되었거나 유효기간이 올바르지 않습니다.")
        expected = self._signature(asset_id, expires_at)
        if not signature or not hmac.compare_digest(expected, signature):
            raise MediaAssetError("미디어 URL 서명을 확인할 수 없습니다.")
        return self.get_asset(asset_id)
