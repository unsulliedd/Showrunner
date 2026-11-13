"""Theme tokens: color roles derived from three base colors for a light and a dark set, and the size scale.

So that any base color stays readable, roles keep an OKLCH lightness bound: text and marks drawn from a
base color at most 0.58 in light and at least 0.70 in dark, pale fills behind text at least 0.88 in light
and at most 0.45 in dark, and text on a base-color fill turns from white to the dark ink once the fill's
lightness passes 0.6. The bounds are close to, but not exactly, 4.5:1 for every hue, so each text role is
then moved further in lightness until it reaches 4.5:1 on the backgrounds it is drawn on.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from showrunner.ui.theme.color import WHITE, at_least, at_most, contrast, hex_to_oklch, mix, with_lightness

TEXT_CONTRAST = 4.5
DARK_INK = "#1b1f24"
_INK_SWITCH_LIGHTNESS = 0.6


class Base(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    ACCENT = "accent"


class ColorSet(StrEnum):
    LIGHT = "light"
    DARK = "dark"


DEFAULT_BASES: dict[Base, str] = {Base.PRIMARY: "#2b3a8f", Base.SECONDARY: "#6fc3d8", Base.ACCENT: "#e0a43a"}


@dataclass(frozen=True)
class ThemeColors:
    """The user's changes only: base colors and per-role overrides of each set that differ from the defaults."""

    base: dict[Base, str] = field(default_factory=dict)
    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)

    def overrides(self, color_set: ColorSet) -> dict[str, str]:
        return self.light if color_set is ColorSet.LIGHT else self.dark


def ink_on(fill: str) -> str:
    """White on a dark fill, the dark ink on a light one."""
    return DARK_INK if hex_to_oklch(fill)[0] > _INK_SWITCH_LIGHTNESS else WHITE


def readable(fg: str, *backgrounds: str, darker: bool) -> str:
    """`fg`, moved darker or lighter in OKLCH lightness until it reaches text contrast on every background."""

    def passes(color: str) -> bool:
        return all(contrast(color, bg) >= TEXT_CONTRAST for bg in backgrounds)

    if passes(fg):
        return fg
    lightness = hex_to_oklch(fg)[0]
    # Black or white always passes on the bounded backgrounds, so `high` starts on the passing side.
    low, high = lightness, 0.0 if darker else 1.0
    best = with_lightness(fg, high)
    for _ in range(20):
        mid = (low + high) / 2
        candidate = with_lightness(fg, mid)
        if passes(candidate):
            high, best = mid, candidate
        else:
            low = mid
    return best if passes(best) else ("#000000" if darker else WHITE)


def fill_behind_ink(fill: str) -> str:
    """`fill`, moved away from its ink in lightness until the ink reaches text contrast on it."""
    ink = ink_on(fill)
    return readable(fill, ink, darker=ink == WHITE)


type Rule = str | Callable[[Mapping[str, str]], str]


@dataclass(frozen=True, slots=True)
class Role:
    """A color role. A rule is a fixed color or a function of the base colors and the roles before it."""

    key: str
    light: Rule
    dark: Rule

    def rule(self, color_set: ColorSet) -> Rule:
        return self.light if color_set is ColorSet.LIGHT else self.dark


# Order matters: a rule reads only base colors and roles listed above it.
ROLES: tuple[Role, ...] = (
    Role("chrome", "#f3f4f6", "#1b1e22"),  # toolbars, side panels, the status bar
    Role("chrome_2", "#e8eaee", "#262a30"),  # rows and buttons under the pointer
    Role("surface", "#ffffff", "#131518"),  # lists, tables, fields, dialog pages
    Role("line", "#dde1e6", "#30353c"),
    Role("ink", DARK_INK, "#e6e8eb"),
    Role("muted", "#57606a", "#9ba3ad"),
    Role("line_strong", lambda v: mix(v["muted"], v["surface"], 0.75), lambda v: mix(v["muted"], v["surface"], 0.75)),
    Role(
        "link",
        lambda v: readable(at_most(mix(v["secondary"], "#003a70", 0.40), 0.58), v["surface"], v["chrome"], darker=True),
        lambda v: readable(at_least(v["secondary"], 0.70), v["surface"], v["chrome"], darker=False),
    ),
    Role("focus", lambda v: v["link"], lambda v: v["link"]),
    # Selected text: a pale fill behind the ordinary ink.
    Role(
        "select",
        lambda v: at_least(mix(v["secondary"], WHITE, 0.35), 0.88),
        lambda v: at_most(mix(v["secondary"], v["surface"], 0.35), 0.45),
    ),
    # Checkboxes, sliders, the border of a field being typed in.
    Role("control", lambda v: at_most(v["primary"], 0.58), lambda v: with_lightness(v["primary"], 0.74, -6)),
    Role(
        "control_fill",
        lambda v: fill_behind_ink(v["primary"]),
        lambda v: fill_behind_ink(mix(v["primary"], WHITE, 0.78)),
    ),
    Role("control_ink", lambda v: ink_on(v["control_fill"]), lambda v: ink_on(v["control_fill"])),
    # Selected rows and pressed buttons.
    Role(
        "control_soft",
        lambda v: at_least(mix(v["primary"], v["surface"], 0.09), 0.88),
        lambda v: at_most(mix(v["primary"], v["surface"], 0.55), 0.45),
    ),
    Role(
        "control_soft_ink",
        lambda v: readable(v["control"], v["control_soft"], darker=True),
        lambda v: readable(mix(v["control"], WHITE, 0.30), v["control_soft"], darker=False),
    ),
    # Where a dragged file will land. No widget or style sheet rule draws it yet.
    Role(
        "drop_soft",
        lambda v: at_least(mix(v["secondary"], v["surface"], 0.18), 0.88),
        lambda v: at_most(mix(v["secondary"], v["surface"], 0.16), 0.45),
    ),
    Role("danger", "#c4302b", "#ff7b72"),
    # Behind a delete or discard button under the pointer. No widget or style sheet rule draws it yet.
    Role("danger_soft", lambda v: mix(v["danger"], v["surface"], 0.10), lambda v: mix(v["danger"], v["surface"], 0.10)),
    # Notices and warnings drawn as text.
    Role(
        "accent_ink",
        lambda v: readable(at_most(mix(v["accent"], "#000000", 0.72), 0.565), v["surface"], v["chrome"], darker=True),
        lambda v: readable(at_least(v["accent"], 0.70), v["surface"], v["chrome"], darker=False),
    ),
    Role("tip", lambda v: v["ink"], lambda v: v["ink"]),
    Role("tip_ink", lambda v: v["chrome"], lambda v: v["chrome"]),
    # Theme colors carry no alpha, so a see-through thumb is mixed against the surface instead.
    Role("scroll_thumb", lambda v: mix(v["muted"], v["surface"], 0.70), lambda v: mix(v["muted"], v["surface"], 0.70)),
    Role("scroll_thumb_hover", lambda v: v["muted"], lambda v: v["muted"]),
)

ROLE: dict[str, Role] = {role.key: role for role in ROLES}


def resolve(colors: ThemeColors, color_set: ColorSet) -> dict[str, str]:
    """Every base color and role of `color_set` as `#rrggbb`. An overridden role stops following its
    rule, and roles that follow it take the override."""
    values: dict[str, str] = {base.value: colors.base.get(base, DEFAULT_BASES[base]) for base in Base}
    overrides = colors.overrides(color_set)
    for role in ROLES:
        rule = role.rule(color_set)
        if role.key in overrides:
            values[role.key] = overrides[role.key]
        else:
            values[role.key] = rule if isinstance(rule, str) else rule(values)
    return values


def with_base(colors: ThemeColors, base: Base, hex_color: str | None) -> ThemeColors:
    """`colors` with `base` set, or back to its default when `hex_color` is the default or None."""
    bases = dict(colors.base)
    if hex_color is None or hex_color == DEFAULT_BASES[base]:
        bases.pop(base, None)
    else:
        bases[base] = hex_color
    return ThemeColors(bases, colors.light, colors.dark)


def with_role(colors: ThemeColors, color_set: ColorSet, key: str, hex_color: str | None) -> ThemeColors:
    """`colors` with role `key` of `color_set` overridden, or reset when `hex_color` is None or the role's
    fixed default. A derived role keeps an override equal to today's derived value: that value moves when
    a base color changes, the override does not."""
    roles = dict(colors.overrides(color_set))
    if hex_color is None or hex_color == ROLE[key].rule(color_set):
        roles.pop(key, None)
    else:
        roles[key] = hex_color
    if color_set is ColorSet.LIGHT:
        return ThemeColors(colors.base, roles, colors.dark)
    return ThemeColors(colors.base, colors.light, roles)


# Logical pixels; Qt scales them for the screen.
SIZES: dict[str, int] = {
    "text_xs": 11,  # section labels, keys
    "text_sm": 12,  # hints, the status bar
    "text_md": 13,  # everything else
    "text_lg": 14,  # headings inside dialogs
    "text_xl": 16,  # page titles
    "height_sm": 24,  # small icon buttons
    "height_md": 28,  # buttons and fields
    "height_lg": 32,  # the toolbar
    "radius_sm": 4,  # chips, scrollbar thumbs
    "radius_md": 6,  # buttons, fields and rows
    "radius_lg": 10,  # panels
    "space_xs": 2,
    "space_sm": 4,
    "space_md": 8,
    "space_lg": 12,
    "space_xl": 16,
    "swatch_width": 96,
    "window_width": 1200,
    "window_height": 800,
}

# Tried in order; the first one installed is used.
FONT_FAMILIES: tuple[str, ...] = ("Segoe UI Variable Text", "Segoe UI", "Noto Sans", "Helvetica Neue", "Arial")
