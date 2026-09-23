"""Generate tray icons for MySQL service controller."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw


def _base_icon(fill: tuple[int, int, int], accent: tuple[int, int, int]) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.ellipse((4, 4, 60, 60), fill=fill)
    draw.ellipse((18, 14, 46, 34), fill=accent)
    draw.rectangle((24, 28, 40, 50), fill=accent)
    draw.ellipse((22, 44, 42, 54), fill=accent)
    return img


def icon_running() -> Image.Image:
    return _base_icon((7, 120, 70), (255, 255, 255))


def icon_stopped() -> Image.Image:
    return _base_icon((140, 40, 40), (240, 240, 240))


def icon_mixed() -> Image.Image:
    return _base_icon((180, 120, 20), (255, 255, 255))


def icon_idle() -> Image.Image:
    return _base_icon((50, 90, 140), (230, 230, 230))


def save_ico(path: str) -> None:
    img = icon_idle()
    buffer = BytesIO()
    img.save(buffer, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    with open(path, "wb") as fh:
        fh.write(buffer.getvalue())
