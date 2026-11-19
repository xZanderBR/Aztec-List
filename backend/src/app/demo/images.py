"""
Listing images for the demo seed.

Seeded listings use the real photos in ``app/demo/photos/``, named ``{listing_key}-{n}.jpg``
(or .jpeg/.png/.webp, n starting at 1); they go through the same EXIF-stripping/resizing
pipeline as user uploads. A listing whose photo is missing falls back to a generated
placeholder "product card" (a colored gradient with the title and category). Seeded users
with a ``photos/avatars/{user_key}.*`` file get it as their profile picture.
"""

from __future__ import annotations

import hashlib
import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.image_processing import MAX_IMAGE_HEIGHT, MAX_IMAGE_WIDTH, strip_exif_and_optimize

PHOTOS_DIR = Path(__file__).parent / "photos"
AVATARS_DIR = PHOTOS_DIR / "avatars"
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


def _processed(stem: Path, suffixes: tuple[str, ...]) -> tuple[bytes, str] | None:
    """Return (processed bytes, extension without dot) for the first ``stem.<suffix>`` found."""
    for suffix in suffixes:
        path = stem.with_name(stem.name + suffix)
        if path.is_file():
            processed, extension = strip_exif_and_optimize(path.read_bytes())
            return processed, extension.lstrip(".")  # ".jpg" -> "jpg"
    return None


def real_photo(listing_key: str, variant: int) -> tuple[bytes, str] | None:
    """Return (processed bytes, file extension) for a provided real photo, if any."""
    return _processed(PHOTOS_DIR / f"{listing_key}-{variant}", _PHOTO_SUFFIXES)


def profile_picture(user_key: str) -> tuple[bytes, str] | None:
    """
    Return (processed bytes, file extension) for ``photos/avatars/{user_key}.*``, if any.

    Processed like a profile picture upload, so an animated GIF stays animated.
    """
    return _processed(AVATARS_DIR / user_key, (*_PHOTO_SUFFIXES, ".gif"))


def listing_image(listing_key: str, title: str, category: str, variant: int) -> tuple[bytes, str]:
    """(bytes, extension) for one seeded listing image: a real photo if present, else a placeholder."""
    return real_photo(listing_key, variant) or (render_placeholder(title, category, variant), "jpg")
