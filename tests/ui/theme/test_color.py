from __future__ import annotations

import itertools

import pytest

from showrunner.ui.theme.color import (
    contrast,
    hex_to_oklch,
    hex_to_rgb,
    linear_to_oklab,
    oklab_to_linear,
    oklch_to_hex,
    parse_hex,
)

SAMPLES = ["#000000", "#ffffff", "#808080", "#ff0000", "#00ff00", "#0000ff", "#2b3a8f", "#6fc3d8", "#e0a43a"]


@pytest.mark.parametrize("hex_color", SAMPLES)
def test_hex_survives_oklch_and_back(hex_color: str) -> None:
    assert oklch_to_hex(*hex_to_oklch(hex_color)) == hex_color


def test_linear_rgb_survives_oklab_and_back() -> None:
    for rgb in itertools.product((0.0, 0.1, 0.5, 0.9, 1.0), repeat=3):
        assert oklab_to_linear(*linear_to_oklab(*rgb)) == pytest.approx(rgb, abs=1e-6)


def test_known_oklch_values() -> None:
    assert hex_to_oklch("#ffffff")[0] == pytest.approx(1.0, abs=1e-4)
    lightness, chroma, hue = hex_to_oklch("#ff0000")
    # Reference values from the CSS Color 4 sample code.
    assert (lightness, chroma, hue) == pytest.approx((0.62796, 0.25768, 29.2339), abs=1e-3)


def test_out_of_gamut_keeps_lightness_by_dropping_chroma() -> None:
    result = oklch_to_hex(0.95, 0.4, 260)
    assert all(0 <= c <= 1 for c in hex_to_rgb(result))
    assert hex_to_oklch(result)[0] == pytest.approx(0.95, abs=0.01)


def test_contrast_extremes() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#777777") == pytest.approx(1)


@pytest.mark.parametrize(
    ("text", "expected"), [("#ABCDEF", "#abcdef"), (" #abc ", "#aabbcc"), ("abc", None), ("#abcd", None), ("", None)]
)
def test_parse_hex(text: str, expected: str | None) -> None:
    assert parse_hex(text) == expected
