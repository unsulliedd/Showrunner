from __future__ import annotations

import pytest

from showrunner.ui.theme.color import contrast, hex_to_oklch, oklch_to_hex
from showrunner.ui.theme.tokens import (
    DEFAULT_BASES,
    QUICK_ROLES,
    ROLES,
    TEXT_CONTRAST,
    Base,
    ColorSet,
    ThemeColors,
    resolve,
    with_base,
    with_role,
)

# Text roles and the backgrounds the style sheet and palette draw them on.
TEXT_ON_BACKGROUND = [
    ("ink", "surface"),
    ("ink", "chrome"),
    ("ink", "chrome_2"),
    ("ink", "select"),
    ("ink", "drop_soft"),
    ("ink", "danger_soft"),
    ("muted", "surface"),
    ("muted", "chrome"),
    ("link", "surface"),
    ("link", "chrome"),
    ("accent_ink", "surface"),
    ("accent_ink", "chrome"),
    ("danger", "surface"),
    ("control_ink", "control_fill"),
    ("control_soft_ink", "control_soft"),
    ("tip_ink", "tip"),
]

# Pure colors, greys, and an OKLCH grid of hues, lightness levels (around the 0.6 ink switch too) and chromas.
BASE_COLORS = sorted(
    {"#ffffff", "#000000", "#808080", "#ffff00", "#00ffff", "#ff00ff", "#0000ff", "#ff0000", "#00ff00"}
    | {
        oklch_to_hex(lightness, chroma, hue)
        for hue in range(0, 360, 45)
        for lightness in (0.15, 0.4, 0.57, 0.6, 0.62, 0.8, 0.95)
        for chroma in (0.0, 0.1, 0.3)
    }
)


@pytest.mark.parametrize("color_set", list(ColorSet))
def test_every_text_role_is_readable_for_any_base_color(color_set: ColorSet) -> None:
    failures = []
    for hex_color in BASE_COLORS:
        roles = resolve(ThemeColors(dict.fromkeys(Base, hex_color)), color_set)
        for fg, bg in TEXT_ON_BACKGROUND:
            ratio = contrast(roles[fg], roles[bg])
            if ratio < TEXT_CONTRAST:
                failures.append(f"{hex_color}: {fg} on {bg} is {ratio:.2f}")
    assert failures == []


@pytest.mark.parametrize("color_set", list(ColorSet))
def test_every_role_resolves_to_a_hex_color(color_set: ColorSet) -> None:
    roles = resolve(ThemeColors(), color_set)
    for role in ROLES:
        assert len(roles[role.key]) == 7
        assert roles[role.key].startswith("#")


def test_bases_follow_into_derived_roles() -> None:
    changed = resolve(with_base(ThemeColors(), Base.PRIMARY, "#7a1f1f"), ColorSet.LIGHT)
    assert changed["control_fill"] == "#7a1f1f"
    assert changed["control_fill"] != resolve(ThemeColors(), ColorSet.LIGHT)["control_fill"]


def test_override_replaces_a_role_and_its_followers_take_it() -> None:
    colors = with_role(ThemeColors(), ColorSet.DARK, "link", "#abcdef")
    dark = resolve(colors, ColorSet.DARK)
    assert dark["link"] == "#abcdef"
    assert dark["focus"] == "#abcdef"
    assert resolve(colors, ColorSet.LIGHT)["link"] != "#abcdef"


def test_changes_stay_sparse() -> None:
    colors = with_base(ThemeColors(), Base.ACCENT, "#123456")
    assert colors.base == {Base.ACCENT: "#123456"}
    assert with_base(colors, Base.ACCENT, DEFAULT_BASES[Base.ACCENT]) == ThemeColors()
    assert with_role(ThemeColors(), ColorSet.LIGHT, "surface", "#ffffff") == ThemeColors()
    assert with_role(with_role(ThemeColors(), ColorSet.LIGHT, "ink", "#000000"), ColorSet.LIGHT, "ink", None) == (
        ThemeColors()
    )


# The approved dark token set of the Qt Quick window.
APPROVED_DARK = {
    "ground": "#0B0D10", "panel": "#12151A", "panel_2": "#191D23", "panel_3": "#21262E", "well": "#0E1014",
    "line": "#22272F", "line_strong": "#353C47", "ink": "#E7EAEE", "muted": "#A2ABB7", "faint": "#7E8894",
    "control": "#8FA8FF", "control_ink": "#0B0D10", "control_soft": "#1B2236", "select": "#1D2540",
    "change": "#F4B544", "change_soft": "#2B2314", "drop": "#FF8077", "drop_soft": "#2C1817",
    "add": "#62D6A5", "add_soft": "#13281F", "video": "#000000",
}  # fmt: skip


def test_the_default_dark_set_is_the_approved_one() -> None:
    dark = resolve(ThemeColors(), ColorSet.DARK)
    assert set(QUICK_ROLES) == set(APPROVED_DARK)
    assert {key: dark[key] for key in QUICK_ROLES} == {key: value.lower() for key, value in APPROVED_DARK.items()}


@pytest.mark.parametrize("color_set", list(ColorSet))
def test_text_levels_are_readable_on_panels(color_set: ColorSet) -> None:
    roles = resolve(ThemeColors(), color_set)
    for text in ("ink", "muted", "faint"):
        for ground in ("panel", "panel_2"):
            assert contrast(roles[text], roles[ground]) >= TEXT_CONTRAST, (text, ground)


def test_dark_roles_follow_a_moved_base() -> None:
    moved = resolve(with_base(ThemeColors(), Base.NEUTRAL, "#101820"), ColorSet.DARK)
    assert moved["ground"] == "#101820"
    assert moved["panel"] != APPROVED_DARK["panel"].lower()
    # Text levels keep their lightness when the neutral moves; only their tint follows.
    assert abs(hex_to_oklch(moved["ink"])[0] - hex_to_oklch(APPROVED_DARK["ink"])[0]) < 0.01
    tinted = resolve(with_base(ThemeColors(), Base.PRIMARY, "#ff8fa8"), ColorSet.DARK)
    assert tinted["control"] == "#ff8fa8"
    assert tinted["select"] != APPROVED_DARK["select"].lower()
