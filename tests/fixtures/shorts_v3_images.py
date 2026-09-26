"""Shorts V3 테스트용 이미지(6-52, 6-53) - 바이너리를 저장소에 두지 않고 테스트 때 임시 폴더에 만든다.

    from tests.fixtures.shorts_v3_images import make_images
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def make_images(folder: Path) -> None:
    """folder/images/{landscape,portrait,square}.png + 이미지가 아닌 파일(not_an_image.png)."""
    images = Path(folder) / "images"
    images.mkdir(parents=True, exist_ok=True)
    land = Image.new("RGB", (1600, 900), (40, 90, 140))
    ImageDraw.Draw(land).ellipse((600, 200, 1000, 600), fill=(240, 180, 60))
    land.save(images / "landscape.png")
    port = Image.new("RGB", (700, 1200), (120, 40, 80))
    ImageDraw.Draw(port).rectangle((200, 300, 500, 900), fill=(60, 200, 160))
    port.save(images / "portrait.png")
    square = Image.new("RGB", (1000, 1000), (30, 30, 60))
    d = ImageDraw.Draw(square)
    d.rectangle((100, 600, 400, 900), fill=(230, 90, 60))  # 왼쪽 아래(기준점 테스트용)
    d.ellipse((600, 100, 900, 400), fill=(90, 220, 120))
    square.save(images / "square.png")
    (images / "not_an_image.png").write_bytes(b"not a png")
