"""Screenshot pixels and the rectangle they came from."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image


@dataclass
class Shot:
    text: str
    jpeg: bytes
    width: int
    height: int


def image_to_screen(x: int, y: int, capture: dict) -> tuple[int, int]:
    width = max(int(capture["iw"]), 1)
    height = max(int(capture["ih"]), 1)
    x = max(0, min(int(x), width - 1))
    y = max(0, min(int(y), height - 1))
    sx = int(capture["ox"]) + int(round(x * int(capture["rw"]) / width))
    sy = int(capture["oy"]) + int(round(y * int(capture["rh"]) / height))
    return sx, sy


def to_jpeg(image: Image.Image) -> tuple[bytes, int, int]:
    frame = image.convert("RGB")
    buffer = BytesIO()
    frame.save(buffer, format="JPEG", quality=70)
    return buffer.getvalue(), frame.width, frame.height
