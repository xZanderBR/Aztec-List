"""
Image processing utilities.

This module provides utilities for optimizing, resizing, and processing images.

Key features:
- Intelligent optimization: Only processes images that need it (based on format, size, dimensions)
- Format preservation: Keeps GIF (animations), suitable WEBPs and small JPEGs in their format
- Metadata stripping: Every output drops EXIF (incl. GPS location), XMP and comments
- Auto-rotation: Respects EXIF orientation before removing metadata
- Dimension limits: Resizes images exceeding MAX_IMAGE_WIDTH x MAX_IMAGE_HEIGHT
- Quality balance: Uses high-quality JPEG compression (85) for good size/quality ratio

Processing flow:
1. Analyze format and dimensions to determine if optimization is needed
2. If not needed, strip metadata without re-compressing:
   - small JPEG: re-saved with its own quantization tables, minus EXIF/XMP/comments
     (returned unchanged when it carries none)
   - small WEBP: EXIF/XMP chunks removed from the RIFF container (lossless, keeps animation)
   - GIF: returned unchanged (the format has no EXIF)
3. If needed: apply EXIF orientation, resize, convert to RGB, compress as JPEG

Used by storage module for all image uploads (listings and profile pictures).
"""

from __future__ import annotations

import io
import logging
import struct

from PIL import ExifTags, Image, ImageOps

logger = logging.getLogger(__name__)

MAX_IMAGE_WIDTH = 815
MAX_IMAGE_HEIGHT = 910
THUMBNAIL_SIZE = (300, 300)
JPEG_QUALITY = 85
THUMBNAIL_QUALITY = 80
RESAMPLING_FILTER = Image.Resampling.LANCZOS

SIZE_THRESHOLD_FOR_OPTIMIZATION = 1920
ALREADY_OPTIMIZED_SIZE_KB = 500


def should_optimize_image(img: Image.Image, file_size: int, format_name: str | None) -> bool:
    """
    Determine if an image needs optimization.

    Args:
        img: PIL Image object
        file_size: Original file size in bytes
        format_name: Image format (e.g., 'JPEG', 'PNG')

    Returns:
        bool: True if image should be optimized
    """
    if format_name == "PNG":
        return True

    # Preserve modern formats unless dimensions exceed limits
    if format_name == "WEBP":
        return img.width > MAX_IMAGE_WIDTH or img.height > MAX_IMAGE_HEIGHT

    # Preserve GIFs (may be animated)
    if format_name == "GIF":
        return False

    if format_name == "JPEG":
        file_size_kb = file_size / 1024
        if img.getexif().get(ExifTags.Base.Orientation, 1) != 1:
            # Rotation lives in the EXIF we strip, so apply it by re-encoding.
            logger.info("Image needs optimization: EXIF orientation must be applied")
        elif img.width > MAX_IMAGE_WIDTH or img.height > MAX_IMAGE_HEIGHT:
            logger.info(
                "Image needs optimization: dimensions %dx%d exceed max %dx%d",
                img.width,
                img.height,
                MAX_IMAGE_WIDTH,
                MAX_IMAGE_HEIGHT,
            )
        elif file_size_kb < ALREADY_OPTIMIZED_SIZE_KB:
            logger.info("Skipping optimization: JPEG is already small (%.1f KB)", file_size_kb)
            return False
        else:
            # Large JPEG file might benefit from optimization
            logger.info("JPEG file is large (%.1f KB), will optimize", file_size_kb)

    # Other formats, rotated/oversized/large JPEGs: optimize
    return True


_FORMAT_EXTENSIONS = {"GIF": ".gif", "WEBP": ".webp", "PNG": ".png", "JPEG": ".jpg"}

# JPEG APP segments with no personal data that affect decoding or color: the JFIF header
# and Adobe's color-transform marker. ICC color profiles (APP2) are kept too, see below.
_HARMLESS_JPEG_SEGMENTS = ("APP0", "APP14")
_ICC_SEGMENT_PREFIX = b"ICC_PROFILE\0"

# WEBP is a RIFF container: "RIFF" <u32 size> "WEBP", then chunks of <fourcc><u32 size><data>
# padded to even length. EXIF and XMP live in their own chunks, flagged in the VP8X header.
_RIFF_HEADER_LEN = 12
_CHUNK_HEADER_LEN = 8
_WEBP_METADATA_CHUNKS = (b"EXIF", b"XMP ")
_VP8X_METADATA_FLAGS = 0x08 | 0x04  # EXIF, XMP


def _jpeg_has_metadata(img: Image.Image) -> bool:
    """Whether a JPEG carries any APP/COM segment beyond JFIF, Adobe and ICC color data."""
    for marker, content in getattr(img, "applist", []):
        if marker in _HARMLESS_JPEG_SEGMENTS:
            continue
        if marker == "APP2" and content.startswith(_ICC_SEGMENT_PREFIX):
            continue
        return True
    return False


def _strip_jpeg_metadata(img: Image.Image, file_content: bytes) -> bytes:
    """Re-save a JPEG without EXIF/XMP/comments, reusing its own quantization tables."""
    if not _jpeg_has_metadata(img):
        return file_content
    output = io.BytesIO()
    # quality="keep" reuses the file's quantization tables and subsampling, so this doesn't
    # compress it any further. Pillow only writes EXIF/XMP when they're passed explicitly.
    img.save(
        output,
        format="JPEG",
        quality="keep",
        icc_profile=img.info.get("icc_profile"),
        comment=b"",
    )
    return output.getvalue()


def _strip_webp_metadata(data: bytes) -> bytes | None:
    """
    Drop the EXIF and XMP chunks from a WEBP losslessly (animation frames untouched).

    Returns ``None`` if the RIFF container doesn't parse.
    """
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or len(data) < _RIFF_HEADER_LEN:
        return None
    (riff_size,) = struct.unpack_from("<I", data, 4)
    end_of_riff = min(len(data), _CHUNK_HEADER_LEN + riff_size)
    chunks: list[bytes] = []
    changed = False
    offset = _RIFF_HEADER_LEN
    while offset < end_of_riff:
        if offset + _CHUNK_HEADER_LEN > end_of_riff:
            return None
        fourcc = data[offset : offset + 4]
        (size,) = struct.unpack_from("<I", data, offset + 4)
        payload_end = offset + _CHUNK_HEADER_LEN + size
        if payload_end > end_of_riff:
            return None
        chunk_end = min(payload_end + (size & 1), end_of_riff)
        chunk = data[offset:chunk_end]
        offset = chunk_end
        if fourcc in _WEBP_METADATA_CHUNKS:
            changed = True
            continue
        if fourcc == b"VP8X" and size and chunk[_CHUNK_HEADER_LEN] & _VP8X_METADATA_FLAGS:
            flags = chunk[_CHUNK_HEADER_LEN] & ~_VP8X_METADATA_FLAGS
            chunk = chunk[:_CHUNK_HEADER_LEN] + bytes([flags]) + chunk[_CHUNK_HEADER_LEN + 1 :]
            changed = True
        chunks.append(chunk)
    if not changed:
        return data
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _strip_metadata_preserving_format(
    img: Image.Image, file_content: bytes, original_format: str | None
) -> tuple[bytes, str] | None:
    """
    Drop metadata from an image that keeps its original format.

    Returns (bytes, extension with dot), or ``None`` when the format can't be cleaned
    without re-encoding (the caller then runs the full optimization instead).
    """
    extension = _FORMAT_EXTENSIONS.get(original_format or "JPEG", ".jpg")
    if original_format == "JPEG":
        return _strip_jpeg_metadata(img, file_content), extension
    if original_format == "WEBP":
        stripped = _strip_webp_metadata(file_content)
        return None if stripped is None else (stripped, extension)
    if original_format == "GIF":
        return file_content, extension  # no EXIF in the format; keeps animations intact
    return None


def strip_exif_and_optimize(
    file_content: bytes,
    max_width: int = MAX_IMAGE_WIDTH,
    max_height: int = MAX_IMAGE_HEIGHT,
    quality: int = JPEG_QUALITY,
) -> tuple[bytes, str]:
    """
    Strip EXIF metadata and optimize image for web.

    This function:
    - Determines if optimization is needed based on format and size
    - Removes all EXIF metadata (privacy/security)
    - Converts to RGB mode if needed
    - Resizes if too large
    - Compresses to JPEG with optimization (only if needed)
    - Auto-rotates based on EXIF orientation (before stripping)

    Args:
        file_content: Original image file bytes
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels
        quality: JPEG quality (1-100, higher = better quality)

    Returns:
        tuple[bytes, str]: Tuple of (optimized image bytes, file extension with dot)

    Raises:
        Exception: If image processing fails
    """
    try:
        img = Image.open(io.BytesIO(file_content))
        original_format = img.format

        needs_optimization = should_optimize_image(img, len(file_content), original_format)

        # Keep the original format (GIF animations, small WEBPs/JPEGs), minus its metadata
        if not needs_optimization:
            preserved = _strip_metadata_preserving_format(img, file_content, original_format)
            if preserved is not None:
                logger.info(
                    "Image doesn't need optimization, preserving original format: %s (%d KB)",
                    original_format,
                    len(file_content) // 1024,
                )
                return preserved
            logger.info("Can't strip %s metadata in place; re-encoding", original_format)

        logger.info("Performing full image optimization")

        # Apply EXIF orientation before it's dropped (MPO = multi-picture JPEG from phones)
        if original_format in ("JPEG", "MPO", "TIFF"):
            img = ImageOps.exif_transpose(img)

        # Convert to RGB for optimization (all optimized images become JPEG)
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if dimensions exceed limits
        if img.width > max_width or img.height > max_height:
            original_size = (img.width, img.height)
            img.thumbnail((max_width, max_height), RESAMPLING_FILTER)
            logger.info(
                "Resized image from %dx%d to %dx%d",
                original_size[0],
                original_size[1],
                img.width,
                img.height,
            )

        # Save as optimized JPEG. Pillow never writes EXIF/XMP unless asked, but it copies a
        # JPEG comment over from the source, so blank it.
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True, comment=b"")
        output.seek(0)

        optimized_size = len(output.getvalue())
        original_size = len(file_content)
        savings_percent = ((original_size - optimized_size) / original_size) * 100
        logger.info(
            "Optimization complete: %d KB -> %d KB (%.1f%% reduction)",
            original_size // 1024,
            optimized_size // 1024,
            savings_percent,
        )

        return output.getvalue(), ".jpg"

    except Exception:
        logger.exception("Image processing failed")
        raise


def create_thumbnail(
    file_content: bytes,
    size: tuple[int, int] = THUMBNAIL_SIZE,
    quality: int = THUMBNAIL_QUALITY,
) -> bytes:
    """
    Create a thumbnail from image.

    Args:
        file_content: Original image file bytes
        size: Thumbnail size as (width, height) tuple
        quality: JPEG quality (1-100)

    Returns:
        bytes: Thumbnail as JPEG bytes

    Raises:
        Exception: If thumbnail generation fails
    """
    try:
        img = Image.open(io.BytesIO(file_content))

        img = ImageOps.exif_transpose(img)

        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail(size, RESAMPLING_FILTER)

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        output.seek(0)

        return output.getvalue()

    except Exception:
        logger.exception("Thumbnail creation failed")
        raise


def get_image_dimensions(file_content: bytes) -> tuple[int, int]:
    """
    Get image dimensions without loading full image.

    Args:
        file_content: Image file bytes

    Returns:
        tuple[int, int]: Width and height in pixels

    Raises:
        Exception: If reading dimensions fails
    """
    try:
        img = Image.open(io.BytesIO(file_content))
    except Exception:
        logger.exception("Failed to read image dimensions")
        raise
    else:
        return img.size
