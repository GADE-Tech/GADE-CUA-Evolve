"""Image preprocessing compatible with Qwen VL."""

import base64
import math
from io import BytesIO

from PIL import Image

from gade_cua_evolve.config import ImageConfig


def round_by_factor(number: float, factor: int) -> int:
    return round(number / factor) * factor


def ceil_by_factor(number: float, factor: int) -> int:
    return math.ceil(number / factor) * factor


def floor_by_factor(number: float, factor: int) -> int:
    return math.floor(number / factor) * factor


def smart_resize(
    height: int,
    width: int,
    factor: int = 28,
    min_pixels: int = 56 * 56,
    max_pixels: int = 14 * 14 * 4 * 1280,
    max_long_side: int = 8192,
) -> tuple[int, int]:
    if height < 2 or width < 2:
        raise ValueError("Image dimensions must both be at least 2")
    if max(height, width) / min(height, width) > 200:
        raise ValueError("Image aspect ratio must not exceed 200")
    if max(height, width) > max_long_side:
        scale = max(height, width) / max_long_side
        height, width = int(height / scale), int(width / scale)
    resized_h = round_by_factor(height, factor)
    resized_w = round_by_factor(width, factor)
    if resized_h * resized_w > max_pixels:
        scale = math.sqrt((height * width) / max_pixels)
        resized_h = floor_by_factor(height / scale, factor)
        resized_w = floor_by_factor(width / scale, factor)
    elif resized_h * resized_w < min_pixels:
        scale = math.sqrt(min_pixels / (height * width))
        resized_h = ceil_by_factor(height * scale, factor)
        resized_w = ceil_by_factor(width * scale, factor)
    return resized_h, resized_w


def process_image(data: bytes, config: ImageConfig) -> tuple[str, int, int, int, int]:
    image = Image.open(BytesIO(data))
    original_width, original_height = image.size
    resized_height, resized_width = smart_resize(
        original_height,
        original_width,
        config.factor,
        config.min_pixels,
        config.max_pixels,
        config.max_long_side,
    )
    image = image.resize((resized_width, resized_height))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return (
        base64.b64encode(buffer.getvalue()).decode("utf-8"),
        original_width,
        original_height,
        resized_width,
        resized_height,
    )
