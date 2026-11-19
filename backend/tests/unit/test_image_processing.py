"""Tests for image processing: every path out of strip_exif_and_optimize drops metadata."""

import io

import pytest
from PIL import ExifTags, Image, ImageCms

from app.core.image_processing import strip_exif_and_optimize

XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><exif:GPSLatitude>32,46.5N</exif:GPSLatitude></x:xmpmeta>'
)


def _gps_exif(orientation: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "TestPhone"
    exif[ExifTags.Base.Orientation] = orientation
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (32.0, 46.0, 30.0)
    return exif


def _encode(image: Image.Image, fmt: str, **params: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **params)
    return buffer.getvalue()


def _frames(size: tuple[int, int] = (120, 90)) -> list[Image.Image]:
    return [Image.new("RGB", size, color) for color in ("red", "green", "blue")]


def _assert_no_metadata(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    assert not image.getexif()
    assert "exif" not in image.info
    assert "xmp" not in image.info
    assert "comment" not in image.info
    return image


@pytest.mark.unit
class TestSmallJpeg:
    """JPEGs small enough to skip re-compression."""

    def test_strips_exif_gps_xmp_and_comment(self) -> None:
        original = _encode(
            Image.new("RGB", (200, 150), "red"),
            "JPEG",
            exif=_gps_exif(),
            xmp=XMP,
            comment=b"taken at home",
        )

        data, extension = strip_exif_and_optimize(original)

        assert extension == ".jpg"
        image = _assert_no_metadata(data)
        assert image.format == "JPEG"
        assert image.size == (200, 150)

    def test_keeps_original_quantization(self) -> None:
        original_image = Image.new("RGB", (200, 150), "red")
        original = _encode(original_image, "JPEG", quality=95, exif=_gps_exif())

        data, _ = strip_exif_and_optimize(original)

        before = Image.open(io.BytesIO(original))
        after = Image.open(io.BytesIO(data))
        assert after.quantization == before.quantization

    def test_keeps_icc_profile(self) -> None:
        icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        original = _encode(
            Image.new("RGB", (200, 150), "red"), "JPEG", exif=_gps_exif(), icc_profile=icc
        )

        data, _ = strip_exif_and_optimize(original)

        assert Image.open(io.BytesIO(data)).info.get("icc_profile") == icc

    def test_clean_jpeg_is_returned_unchanged(self) -> None:
        original = _encode(Image.new("RGB", (200, 150), "red"), "JPEG")

        data, extension = strip_exif_and_optimize(original)

        assert data == original
        assert extension == ".jpg"

    def test_applies_orientation_before_dropping_it(self) -> None:
        # Orientation 6 = rotate 90° clockwise to display; dropping the tag without
        # rotating would show the photo sideways.
        original = _encode(Image.new("RGB", (200, 100), "red"), "JPEG", exif=_gps_exif(6))

        data, _ = strip_exif_and_optimize(original)

        assert _assert_no_metadata(data).size == (100, 200)


@pytest.mark.unit
class TestOptimizedJpeg:
    def test_large_jpeg_is_resized_and_stripped(self) -> None:
        original = _encode(
            Image.new("RGB", (2000, 1500), "red"),
            "JPEG",
            exif=_gps_exif(),
            xmp=XMP,
            comment=b"taken at home",
        )

        data, extension = strip_exif_and_optimize(original)

        assert extension == ".jpg"
        image = _assert_no_metadata(data)
        assert image.width <= 815
        assert image.height <= 910

    def test_mpo_orientation_is_applied(self) -> None:
        # Phones save multi-picture JPEGs (MPO); Pillow reports them as "MPO", not "JPEG".
        frames = _frames((200, 100))
        original = _encode(
            frames[0], "MPO", save_all=True, append_images=frames[1:2], exif=_gps_exif(6)
        )

        data, extension = strip_exif_and_optimize(original)

        assert extension == ".jpg"
        assert _assert_no_metadata(data).size == (100, 200)


@pytest.mark.unit
class TestSmallWebp:
    def test_strips_exif_and_xmp(self) -> None:
        original = _encode(Image.new("RGB", (200, 150), "blue"), "WEBP", exif=_gps_exif(), xmp=XMP)

        data, extension = strip_exif_and_optimize(original)

        assert extension == ".webp"
        image = _assert_no_metadata(data)
        assert image.format == "WEBP"
        assert image.size == (200, 150)

    def test_animated_webp_keeps_frames(self) -> None:
        frames = _frames()
        original = _encode(
            frames[0],
            "WEBP",
            save_all=True,
            append_images=frames[1:],
            exif=_gps_exif(),
            duration=100,
        )

        data, extension = strip_exif_and_optimize(original)

        assert extension == ".webp"
        assert _assert_no_metadata(data).n_frames == len(frames)

    def test_clean_webp_is_returned_unchanged(self) -> None:
        original = _encode(Image.new("RGB", (200, 150), "blue"), "WEBP")

        data, _ = strip_exif_and_optimize(original)

        assert data == original


@pytest.mark.unit
class TestGif:
    def test_animated_gif_is_preserved(self) -> None:
        frames = _frames()
        original = _encode(frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100)

        data, extension = strip_exif_and_optimize(original)

        assert extension == ".gif"
        assert Image.open(io.BytesIO(data)).n_frames == len(frames)
