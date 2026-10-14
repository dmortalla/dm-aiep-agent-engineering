"""Local, deterministic image decoding and pixel analysis (Story 9.3).

This is genuine processing of the submitted pixels, not fixture lookup: the image is decoded with
Pillow (restricted to the declared, allowlisted format), its dimensions are bounded before any
pixel data is decoded, the EXIF orientation is applied, and a bounded thumbnail is analyzed for
brightness, contrast, colorfulness, named dominant colors, per-quadrant colors, and edge density.

It is classical pixel statistics. No vision model runs, so the result describes visual properties
(color, layout, detail) and never claims to recognize objects, text, people, or scenes.
"""

import colorsys
import io
import math
import struct
from collections import Counter
from enum import StrEnum
from typing import Final

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field

from multimodal_voice_platform.adapters.local.errors import (
    MalformedContentError,
    ProcessingLimitError,
    UnsupportedContentError,
)
from multimodal_voice_platform.adapters.local.limits import LocalProcessingLimits

ANALYSIS_EDGE: Final = 128
"""Longest edge, in pixels, of the thumbnail used for statistics. Bounds analysis cost."""

PILLOW_FORMATS: Final = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
"""Pillow decoder allowed for each allowlisted image media type. No other decoder is enabled."""

_DECODE_ERRORS: Final = (
    OSError,
    ValueError,
    SyntaxError,
    EOFError,
    IndexError,
    struct.error,
)
"""Exceptions Pillow raises for malformed, truncated, or hostile image data."""

_HUE_BANDS: Final = ((70, "yellow"), (170, "green"), (200, "cyan"), (260, "blue"), (290, "purple"))
_EDGE_THRESHOLD: Final = 32
_MAX_DOMINANT: Final = 5
_MIN_SHARE: Final = 0.01


class ColorShare(BaseModel):
    """Share of analyzed pixels closest to one named color."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    color: str = Field(min_length=1, max_length=20)
    share: float = Field(ge=0, le=1)


class RegionColor(BaseModel):
    """Dominant named color of one image quadrant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    region: str = Field(min_length=1, max_length=20)
    color: str = Field(min_length=1, max_length=20)
    share: float = Field(ge=0, le=1)


class Orientation(StrEnum):
    """Image orientation from its full-size dimensions."""

    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class ImageAnalysis(BaseModel):
    """Structured result of local pixel analysis. Derived from untrusted content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    media_type: str
    decoder_format: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    orientation: Orientation
    frame_count: int = Field(ge=1)
    has_alpha: bool
    transparent_share: float = Field(ge=0, le=1)
    analyzed_width: int = Field(gt=0, le=ANALYSIS_EDGE)
    analyzed_height: int = Field(gt=0, le=ANALYSIS_EDGE)
    mean_luma: float = Field(ge=0, le=255)
    luma_stddev: float = Field(ge=0)
    brightness: str
    contrast: str
    colorfulness: float = Field(ge=0)
    colorfulness_label: str
    edge_density: float = Field(ge=0, le=1)
    detail: str
    dominant_colors: tuple[ColorShare, ...] = Field(min_length=1, max_length=_MAX_DOMINANT)
    regions: tuple[RegionColor, ...] = Field(default=(), max_length=4)


def color_name(red: int, green: int, blue: int) -> str:
    """Map an RGB pixel to a coarse named color using hue, saturation, and value.

    Args:
        red: Red channel, 0 to 255.
        green: Green channel, 0 to 255.
        blue: Blue channel, 0 to 255.

    Returns:
        One of black, white, gray, red, orange, brown, yellow, green, cyan, blue, purple, magenta.
    """
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    if value < 0.2:
        return "black"
    if saturation < 0.2:
        if value > 0.85:
            return "white"
        return "gray"
    degrees = hue * 360
    if degrees < 15 or degrees >= 345:
        return "brown" if value < 0.5 else "red"
    if degrees < 45:
        return "brown" if value < 0.6 else "orange"
    for upper, name in _HUE_BANDS:
        if degrees < upper:
            return name
    return "magenta"


def analyze_image(data: bytes, media_type: str, limits: LocalProcessingLimits) -> ImageAnalysis:
    """Decode an image and compute bounded pixel statistics.

    Args:
        data: Image bytes, already verified against the declared media type.
        media_type: Declared, allowlisted image media type.
        limits: Processing limits from application configuration.

    Returns:
        The structured pixel analysis.

    Raises:
        UnsupportedContentError: If the media type has no enabled decoder.
        ProcessingLimitError: If the image exceeds the byte or pixel limit.
        MalformedContentError: If the image cannot be decoded.
    """
    decoder = PILLOW_FORMATS.get(media_type)
    if decoder is None:
        raise UnsupportedContentError("image media type has no enabled decoder")
    if len(data) > limits.max_image_bytes:
        raise ProcessingLimitError("image exceeds the processing byte limit")
    try:
        with Image.open(io.BytesIO(data), formats=[decoder]) as image:
            width, height = image.size
            if width * height > limits.max_image_pixels:
                raise ProcessingLimitError("image exceeds the decoded pixel limit")
            frame_count = getattr(image, "n_frames", 1)
            image.load()
            has_alpha = image.mode in {"RGBA", "LA", "PA", "La", "RGBa"} or (
                "transparency" in image.info
            )
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            rgba = oriented.convert("RGBA")
    except Image.DecompressionBombError as exc:
        raise ProcessingLimitError("image exceeds the decoded pixel limit") from exc
    except _DECODE_ERRORS as exc:
        raise MalformedContentError(f"image could not be decoded as {decoder}") from exc
    rgba.thumbnail((ANALYSIS_EDGE, ANALYSIS_EDGE), Image.Resampling.BOX)
    alpha = rgba.getchannel("A").tobytes()
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    rgb = Image.alpha_composite(white, rgba).convert("RGB")
    return _summarize(
        media_type=media_type,
        decoder=decoder,
        size=(width, height),
        frame_count=frame_count,
        has_alpha=has_alpha,
        alpha=alpha,
        rgb=rgb,
    )


def _summarize(
    *,
    media_type: str,
    decoder: str,
    size: tuple[int, int],
    frame_count: int,
    has_alpha: bool,
    alpha: bytes,
    rgb: Image.Image,
) -> ImageAnalysis:
    raw = rgb.tobytes()
    pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
    columns, rows = rgb.size
    lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
    names = [color_name(*pixel) for pixel in pixels]
    mean_luma = sum(lumas) / len(lumas)
    luma_stddev = math.sqrt(sum((value - mean_luma) ** 2 for value in lumas) / len(lumas))
    colorfulness = _colorfulness(pixels)
    edge_density = _edge_density(lumas, columns, rows)
    width, height = size
    if width == height:
        orientation = Orientation.SQUARE
    else:
        orientation = Orientation.LANDSCAPE if width > height else Orientation.PORTRAIT
    return ImageAnalysis(
        media_type=media_type,
        decoder_format=decoder,
        width=width,
        height=height,
        orientation=orientation,
        frame_count=frame_count,
        has_alpha=has_alpha,
        transparent_share=round(sum(1 for a in alpha if a < 128) / len(alpha), 4),
        analyzed_width=columns,
        analyzed_height=rows,
        mean_luma=round(mean_luma, 2),
        luma_stddev=round(luma_stddev, 2),
        brightness=_band(mean_luma, (85, "dark"), (170, "medium brightness"), "bright"),
        contrast=_band(
            luma_stddev, (20, "low contrast"), (60, "moderate contrast"), "high contrast"
        ),
        colorfulness=round(colorfulness, 2),
        colorfulness_label=_band(
            colorfulness, (15, "nearly monochrome"), (50, "moderately colorful"), "highly colorful"
        ),
        edge_density=round(edge_density, 4),
        detail=_band(
            edge_density,
            (0.05, "low detail with large uniform regions"),
            (0.2, "moderate detail"),
            "high detail",
        ),
        dominant_colors=_dominant(names),
        regions=_regions(names, columns, rows),
    )


def _band(value: float, low: tuple[float, str], mid: tuple[float, str], high: str) -> str:
    if value < low[0]:
        return low[1]
    return mid[1] if value < mid[0] else high


def _shares(names: list[str]) -> list[tuple[str, float]]:
    counts = Counter(names)
    total = len(names)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [(name, round(count / total, 4)) for name, count in ordered]


def _dominant(names: list[str]) -> tuple[ColorShare, ...]:
    shares = [ColorShare(color=n, share=s) for n, s in _shares(names) if s >= _MIN_SHARE]
    return tuple(shares[:_MAX_DOMINANT])


def _regions(names: list[str], columns: int, rows: int) -> tuple[RegionColor, ...]:
    if columns < 2 or rows < 2:
        return ()
    mid_x, mid_y = columns // 2, rows // 2
    bounds = {
        "top-left": (0, mid_x, 0, mid_y),
        "top-right": (mid_x, columns, 0, mid_y),
        "bottom-left": (0, mid_x, mid_y, rows),
        "bottom-right": (mid_x, columns, mid_y, rows),
    }
    regions = []
    for region, (x0, x1, y0, y1) in bounds.items():
        cell = [names[y * columns + x] for y in range(y0, y1) for x in range(x0, x1)]
        color, share = _shares(cell)[0]
        regions.append(RegionColor(region=region, color=color, share=share))
    return tuple(regions)


def _colorfulness(pixels: list[tuple[int, int, int]]) -> float:
    """Hasler and Suesstrunk colorfulness metric over RGB pixels."""
    rg = [r - g for r, g, _ in pixels]
    yb = [0.5 * (r + g) - b for r, g, b in pixels]
    mean_rg, mean_yb = sum(rg) / len(rg), sum(yb) / len(yb)
    std_rg = math.sqrt(sum((v - mean_rg) ** 2 for v in rg) / len(rg))
    std_yb = math.sqrt(sum((v - mean_yb) ** 2 for v in yb) / len(yb))
    return math.hypot(std_rg, std_yb) + 0.3 * math.hypot(mean_rg, mean_yb)


def _edge_density(lumas: list[float], columns: int, rows: int) -> float:
    edges = pairs = 0
    for y in range(rows):
        for x in range(columns):
            here = lumas[y * columns + x]
            if x + 1 < columns:
                pairs += 1
                edges += abs(here - lumas[y * columns + x + 1]) >= _EDGE_THRESHOLD
            if y + 1 < rows:
                pairs += 1
                edges += abs(here - lumas[(y + 1) * columns + x]) >= _EDGE_THRESHOLD
    return edges / pairs if pairs else 0.0
