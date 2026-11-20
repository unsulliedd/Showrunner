"""Color math on `#rrggbb` strings: sRGB, OKLab and OKLCH conversions, mixing and WCAG contrast.

OKLab matrices are Björn Ottosson's reference values. Hue is in degrees, as in CSS `oklch()`.
"""

from __future__ import annotations

import math
import re

WHITE = "#ffffff"

_HEX6 = re.compile(r"#[0-9a-f]{6}")
_HEX3 = re.compile(r"#[0-9a-f]{3}")
_GAMUT_EPSILON = 1e-6


def parse_hex(text: str) -> str | None:
    """`text` as lowercase `#rrggbb`, widening `#rgb`; None for anything else."""
    s = text.strip().lower()
    if _HEX6.fullmatch(s):
        return s
    if _HEX3.fullmatch(s):
        return "#" + "".join(ch * 2 for ch in s[1:])
    return None


def hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """Gamma-encoded sRGB channels in 0..1."""
    return int(hex_color[1:3], 16) / 255, int(hex_color[3:5], 16) / 255, int(hex_color[5:7], 16) / 255


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{round(min(max(c, 0.0), 1.0) * 255):02x}" for c in (r, g, b))


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def linear_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    l_ = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_linear(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def oklab_to_oklch(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    return lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def oklch_to_oklab(lightness: float, chroma: float, hue: float) -> tuple[float, float, float]:
    h = math.radians(hue)
    return lightness, chroma * math.cos(h), chroma * math.sin(h)


def hex_to_oklch(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in hex_to_rgb(hex_color))
    return oklab_to_oklch(*linear_to_oklab(r, g, b))


def _linear_from_oklch(lightness: float, chroma: float, hue: float) -> tuple[float, float, float]:
    return oklab_to_linear(*oklch_to_oklab(lightness, chroma, hue))


def _in_gamut(rgb: tuple[float, float, float]) -> bool:
    return all(-_GAMUT_EPSILON <= c <= 1 + _GAMUT_EPSILON for c in rgb)


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """The sRGB color for an OKLCH value. Out of gamut, chroma is reduced until it fits.

    Reducing chroma keeps lightness and hue, so a lightness bound set on a role still holds;
    clipping each channel instead would shift lightness and break the contrast guarantees.
    """
    lightness = min(max(lightness, 0.0), 1.0)
    rgb = _linear_from_oklch(lightness, chroma, hue)
    if not _in_gamut(rgb):
        low, high = 0.0, chroma
        for _ in range(24):
            mid = (low + high) / 2
            if _in_gamut(_linear_from_oklch(lightness, mid, hue)):
                low = mid
            else:
                high = mid
        rgb = _linear_from_oklch(lightness, low, hue)
    return rgb_to_hex(*(_to_gamma(min(max(c, 0.0), 1.0)) for c in rgb))


def with_lightness(hex_color: str, lightness: float, hue_shift: float = 0.0) -> str:
    _, chroma, hue = hex_to_oklch(hex_color)
    return oklch_to_hex(lightness, chroma, hue + hue_shift)


def at_most(hex_color: str, lightness: float) -> str:
    """`hex_color` with its OKLCH lightness lowered to `lightness` when above it."""
    current, chroma, hue = hex_to_oklch(hex_color)
    return hex_color if current <= lightness else oklch_to_hex(lightness, chroma, hue)


def at_least(hex_color: str, lightness: float) -> str:
    """`hex_color` with its OKLCH lightness raised to `lightness` when below it."""
    current, chroma, hue = hex_to_oklch(hex_color)
    return hex_color if current >= lightness else oklch_to_hex(lightness, chroma, hue)


def mix(first: str, second: str, weight: float) -> str:
    """`weight` of `first` and the rest of `second`, mixed in gamma-encoded sRGB as CSS `color-mix(in srgb)`."""
    a, b = hex_to_rgb(first), hex_to_rgb(second)
    return rgb_to_hex(*(x * weight + y * (1 - weight) for x, y in zip(a, b, strict=True)))


def luminance(hex_color: str) -> float:
    """WCAG relative luminance."""
    r, g, b = (_to_linear(c) for c in hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio, 1 to 21."""
    hi, lo = sorted((luminance(first), luminance(second)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
