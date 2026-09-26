"""Shorts V3 asset resolver(6-54) - 문서가 요청한 이미지를 확인하고 메타데이터를 만든다.

    AssetRequest(path, alt, source)  ->  AssetResolver.resolve()  ->  ResolvedAsset
        1) 경로 확인  2) 파일 존재  3) 형식(PNG/JPEG/WEBP)  4) 디코드  5) 크기(템플릿 최소값)
        6) 비율/방향(portrait/landscape/square)  7) sha256
    crop/position 적용은 레이아웃 엔진이 ResolvedAsset + 장면 image 설정으로 한다.

실패는 예외가 아니라 ``status``/``code``로 돌려준다(ASSET_MISSING, ASSET_UNSUPPORTED_FORMAT,
ASSET_DECODE_FAILED, ASSET_TOO_SMALL) - 렌더러는 placeholder로 계속 그리고, 품질 게이트가
템플릿 정책(image.on_missing)에 따라 막거나 경고한다.

같은 파일(경로·크기·수정시각)은 해시를 다시 계산하지 않고, 같은 내용(sha256)은 다시 디코드하지 않는다
(프로세스 안 캐시 - 배치에서 여러 문서가 같은 이미지를 쓸 때).

향후 이미지 자동 수집: ``AssetRequest``에 query/provider를 채우고 ``resolve()`` 앞에 다운로드
단계를 두면 된다(docs/6-54 24장). 지금은 로컬 파일만 읽는다 - 네트워크를 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_FORMATS = ("PNG", "JPEG", "WEBP")
SQUARE_TOLERANCE = 0.05  # |가로/세로 - 1| 이하면 square


@dataclass(frozen=True)
class AssetRequest:
    path: str  # 문서 기준 상대 경로 또는 절대 경로
    base_dir: Path = Path(".")
    alt: str = ""
    source: str = ""


@dataclass(frozen=True)
class ResolvedAsset:
    path: str  # 문서에 적힌 경로(그대로)
    resolved_path: str
    filename: str
    status: str  # ok / missing / unsupported / decode_failed / too_small
    code: str = ""  # status가 ok가 아니면 오류 코드
    message: str = ""
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    orientation: str = ""  # portrait / landscape / square
    format: str = ""
    bytes: int = 0
    sha256: str = ""
    alt: str = ""
    source: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return asdict(self)


def orientation_of(width: int, height: int) -> str:
    ratio = width / height
    if abs(ratio - 1) <= SQUARE_TOLERANCE:
        return "square"
    return "landscape" if ratio > 1 else "portrait"


class AssetResolver:
    def __init__(self, *, min_width: int = 1, min_height: int = 1, formats=SUPPORTED_FORMATS, cache_images: int = 16) -> None:
        self.min_width, self.min_height, self.formats = int(min_width), int(min_height), tuple(formats)
        self._hashes: dict[tuple, str] = {}  # (경로, 크기, 수정시각) -> sha256
        self._images: OrderedDict[str, Image.Image] = OrderedDict()  # sha256 -> 디코드한 RGB 이미지
        self._max_images = cache_images
        self.hash_computations = 0  # 테스트/성능 보고용
        self.decodes = 0

    @classmethod
    def for_template(cls, template: dict) -> "AssetResolver":
        image = template.get("image", {})
        return cls(min_width=image.get("min_width", 1), min_height=image.get("min_height", 1),
                   formats=image.get("formats", SUPPORTED_FORMATS))

    def _sha256(self, path: Path) -> str:
        st = path.stat()
        key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
        if key not in self._hashes:
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            self._hashes[key] = h.hexdigest()
            self.hash_computations += 1
        return self._hashes[key]

    def resolve(self, request: AssetRequest) -> ResolvedAsset:
        p = Path(request.path)
        path = p if p.is_absolute() else Path(request.base_dir) / p
        base = dict(path=request.path, resolved_path=str(path), filename=p.name, alt=request.alt, source=request.source)
        if not path.is_file():
            return ResolvedAsset(**base, status="missing", code="ASSET_MISSING", message=f"이미지 파일이 없습니다: {request.path}")
        sha, size = self._sha256(path), path.stat().st_size
        try:
            with Image.open(path) as img:
                fmt = img.format or ""
                if fmt not in self.formats:
                    return ResolvedAsset(**base, status="unsupported", code="ASSET_UNSUPPORTED_FORMAT", bytes=size, sha256=sha, format=fmt,
                                         message=f"지원하지 않는 이미지 형식 {fmt!r}({', '.join(self.formats)}만): {request.path}")
                img.verify()  # 잘린/깨진 파일 검출(verify 후에는 다시 열어야 한다)
            with Image.open(path) as img:
                img.load()
                w, h = ImageOps.exif_transpose(img).size
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
            return ResolvedAsset(**base, status="decode_failed", code="ASSET_DECODE_FAILED", bytes=size, sha256=sha,
                                 message=f"이미지를 디코드할 수 없습니다: {request.path} ({type(error).__name__})")
        meta = dict(width=w, height=h, aspect_ratio=round(w / h, 4), orientation=orientation_of(w, h), format=fmt, bytes=size, sha256=sha)
        if w < self.min_width or h < self.min_height:
            return ResolvedAsset(**base, **meta, status="too_small", code="ASSET_TOO_SMALL",
                                 message=f"이미지가 너무 작습니다 {w}x{h}(최소 {self.min_width}x{self.min_height}): {request.path}")
        return ResolvedAsset(**base, **meta, status="ok")

    def load(self, asset: ResolvedAsset) -> Image.Image:
        """ok인 asset의 RGB 이미지(EXIF 회전 적용). 같은 sha256이면 다시 디코드하지 않는다."""
        if not asset.ok:
            raise ValueError(f"사용할 수 없는 asset: {asset.status} {asset.path}")
        if asset.sha256 in self._images:
            self._images.move_to_end(asset.sha256)
            return self._images[asset.sha256]
        with Image.open(asset.resolved_path) as src:
            img = ImageOps.exif_transpose(src).convert("RGB")
        self.decodes += 1
        self._images[asset.sha256] = img
        while len(self._images) > self._max_images:
            self._images.popitem(last=False)
        return img


def resolve_assets(doc, resolver: AssetResolver | None = None) -> dict[int, ResolvedAsset]:
    """문서의 장면별 이미지 요청 -> {장면 번호: ResolvedAsset}. 경로가 없는 슬롯은 포함하지 않는다."""
    resolver = resolver or AssetResolver.for_template(doc.template)
    out: dict[int, ResolvedAsset] = {}
    for i, scene in enumerate(doc.scenes):
        if scene.image is not None and scene.image.path:
            out[i] = resolver.resolve(AssetRequest(scene.image.path, doc.base_dir, scene.image.alt, scene.image.source))
    return out


def resolve_asset(request: AssetRequest, resolver: AssetResolver | None = None) -> ResolvedAsset:
    """이미지 요청 1건 -> 확인된 asset. 향후 자동 수집도 이 입구를 지난다(아래 AssetProvider)."""
    return (resolver or AssetResolver()).resolve(request)


class AssetProvider:
    """향후 이미지 자동 수집 연결 지점(6-54 설계만, 구현 없음 - 지금은 로컬 파일만 쓴다).

        CONTENT -> IMAGE QUERY -> provider.search(query) -> 후보 선택 -> provider.fetch(candidate, dest) -> 로컬 파일
                -> AssetRequest(path=<로컬 파일>, source=<출처>, alt=...) -> resolve_asset() -> 렌더

    구현체는 라이선스/저작자/원본 URL을 함께 돌려줘야 하고, 받은 파일은 문서 옆 images/에 저장해
    문서의 image.path로만 렌더러에 들어간다(렌더러는 네트워크를 모른다)."""

    def search(self, query: str, *, limit: int = 5) -> list[dict]:  # {"url", "license", "author", "width", "height"}
        raise NotImplementedError

    def fetch(self, candidate: dict, dest_dir: Path) -> Path:
        raise NotImplementedError
