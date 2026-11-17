"""
Listing images for the demo seed.

Each seeded listing gets generated placeholder "product cards" (a colored gradient with
the title and category), so the repo ships no binary assets. To use real photos instead,
drop files named ``{listing_key}-{n}.jpg`` (or .jpeg/.png/.webp, n starting at 1) into
``app/demo/photos/``; they go through the same EXIF-stripping/resizing pipeline as user
uploads.
"""

from __future__ import annotations

import hashlib
import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.image_processing import MAX_IMAGE_HEIGHT, MAX_IMAGE_WIDTH, strip_exif_and_optimize

PHOTOS_DIR = Path(__file__).parent / "photos"
_PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# Soft two-tone gradients; picked deterministically per listing so resets look identical.
_PALETTES = [
    ((236, 72, 153), (126, 34, 206)),
    ((59, 130, 246), (14, 116, 144)),
    ((16, 185, 129), (21, 94, 117)),
    ((245, 158, 11), (220, 38, 38)),
    ((139, 92, 246), (49, 46, 129)),
    ((20, 184, 166), (37, 99, 235)),
    ((244, 114, 182), (251, 146, 60)),
    ((100, 116, 139), (30, 41, 59)),
]


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    digest = hashlib.sha256(seed.encode()).digest()
    return _PALETTES[digest[0] % len(_PALETTES)]


def _gradient(size: tuple[int, int], top: tuple[int, ...], bottom: tuple[int, ...]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        draw.line([(0, y), (width, y)], fill=color)
    return image


def render_placeholder(title: str, category: str, variant: int) -> bytes:
    """Render a listing placeholder image as JPEG bytes (same size as processed uploads)."""
    size = (MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT)
    top, bottom = _palette(f"{title}:{variant}")
    image = _gradient(size, top, bottom)
    draw = ImageDraw.Draw(image)

    title_font = ImageFont.load_default(size=60)
    small_font = ImageFont.load_default(size=30)
    margin = 64

    label = category.replace("_", " ").upper()
    draw.text((margin, margin), label, font=small_font, fill=(255, 255, 255, 220))

    lines = textwrap.wrap(title, width=20)[:5]
    line_height = 76
    y = (size[1] - line_height * len(lines)) // 2
    for line in lines:
        draw.text((margin, y), line, font=title_font, fill=(255, 255, 255))
        y += line_height

    caption = "Aztec List demo photo" + (f" {variant}" if variant > 1 else "")
    draw.text((margin, size[1] - margin - 30), caption, font=small_font, fill=(255, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True)
    return buffer.getvalue()


def real_photo(listing_key: str, variant: int) -> tuple[bytes, str] | None:
    """Return (processed bytes, file extension) for a provided real photo, if any."""
    for suffix in _PHOTO_SUFFIXES:
        path = PHOTOS_DIR / f"{listing_key}-{variant}{suffix}"
        if path.is_file():
            processed, fmt = strip_exif_and_optimize(path.read_bytes())
            ext = (fmt or "jpeg").lower()
            return processed, "jpg" if ext == "jpeg" else ext
    return None


def listing_image(listing_key: str, title: str, category: str, variant: int) -> tuple[bytes, str]:
    """(bytes, extension) for one seeded listing image: a real photo if present, else a placeholder."""
    return real_photo(listing_key, variant) or (render_placeholder(title, category, variant), "jpg")
