"""Theme tokens: color roles derived from a few base colors for a light and a dark set, and the size scale.

Two generations of roles share this table. The window reads the roles of the approved dark set (`QUICK_ROLES`);
the older roles are read by no window, but the light rules of several window roles still derive from them
(`surface`, `chrome`, `danger`). Keys both use (`ink`, `line`, `control`, ...) carry the
window's values in the dark set.

So that any base color stays readable, the older roles keep an OKLCH lightness bound: text and marks drawn
from a base color at most 0.58 in light and at least 0.70 in dark, pale fills behind text at least 0.88 in
light and at most 0.45 in dark, and text on a base-color fill turns from white to the dark ink once the
fill's lightness passes 0.6. The bounds are close to, but not exactly, 4.5:1 for every hue, so each text
role is then moved further in lightness until it reaches 4.5:1 on the backgrounds it is drawn on.

The dark Qt Quick roles follow their base color instead: each is the approved value at the default base,
moved in hue and chroma (and, for surfaces, lightness) as far as the base moved.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from showrunner.ui.theme.color import (
    WHITE,
    at_least,
    at_most,
    contrast,
    hex_to_oklch,
    luminance,
    mix,
    oklch_to_hex,
    with_lightness,
)

TEXT_CONTRAST = 4.5
DARK_INK = "#1b1f24"
_INK_SWITCH_LIGHTNESS = 0.6


class Base(StrEnum):
    PRIMARY = "primary"  # the control color: selection, focus, the primary action
    SECONDARY = "secondary"  # the light set's selection; Appearance does not offer it
    ACCENT = "accent"  # the change color: whatever a run will change
    NEUTRAL = "neutral"  # the neutral the window ground, panels, lines and text levels are tinted from
    DEFAULT_TRACK = "default_track"  # the code of a track that has the default flag
    FORCED_TRACK = "forced_track"  # the frame of a track's code where the track has the forced flag


class ColorSet(StrEnum):
    LIGHT = "light"
    DARK = "dark"


DEFAULT_BASES: dict[Base, str] = {
    Base.PRIMARY: "#8fa8ff",
    Base.SECONDARY: "#6fc3d8",
    Base.ACCENT: "#f4b544",
    Base.NEUTRAL: "#0b0d10",
    Base.DEFAULT_TRACK: "#5fcfe0",
    Base.FORCED_TRACK: "#e59ad8",
}


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


def follow(base: Base, approved: str, *, lightness: bool = False) -> Rule:
    """`approved` at the default `base`; for another base, moved by the base's hue change and scaled by its chroma
    change, and with `lightness` also shifted by its lightness change (surfaces follow a lighter ground, text
    levels keep their lightness)."""
    default = DEFAULT_BASES[base]
    approved = approved.lower()

    def rule(values: Mapping[str, str]) -> str:
        current = values[base.value]
        if current == default:
            return approved
        base_l, base_c, base_h = hex_to_oklch(current)
        default_l, default_c, default_h = hex_to_oklch(default)
        role_l, role_c, role_h = hex_to_oklch(approved)
        scale = base_c / default_c if default_c else 1.0
        shift = base_l - default_l if lightness else 0.0
        return oklch_to_hex(min(max(role_l + shift, 0.0), 1.0), role_c * scale, role_h + base_h - default_h)

    return rule


@dataclass(frozen=True, slots=True)
class Role:
    """A color role. A rule is a fixed color or a function of the base colors and the roles before it."""

    key: str
    light: Rule
    dark: Rule

    def rule(self, color_set: ColorSet) -> Rule:
        return self.light if color_set is ColorSet.LIGHT else self.dark


_N = Base.NEUTRAL

# Order matters: a rule reads only base colors and roles listed above it. A role named in `QUICK_ROLES` is read by
# the window; the rest are read only by other roles' rules, or by nothing.
ROLES: tuple[Role, ...] = (
    Role("ground", lambda v: with_lightness(v["neutral"], 0.955), lambda v: v["neutral"]),  # between panels
    Role("panel", lambda v: with_lightness(v["neutral"], 0.995), follow(_N, "#12151a", lightness=True)),
    Role("panel_2", lambda v: with_lightness(v["neutral"], 0.975), follow(_N, "#191d23", lightness=True)),  # cards
    Role("panel_3", lambda v: with_lightness(v["neutral"], 0.94), follow(_N, "#21262e", lightness=True)),  # chips
    Role("well", lambda v: with_lightness(v["neutral"], 0.985), follow(_N, "#0e1014", lightness=True)),  # inputs
    Role("chrome", "#f3f4f6", "#1b1e22"),  # toolbars, side panels, the status bar
    Role("surface", "#ffffff", "#131518"),  # lists, tables, fields, dialog pages
    Role("line", "#dde1e6", follow(_N, "#22272f", lightness=True)),
    Role("ink", DARK_INK, follow(_N, "#e7eaee")),
    Role("muted", "#57606a", follow(_N, "#a2abb7")),
    Role(
        "faint",
        lambda v: readable(mix(v["muted"], v["panel"], 0.8), v["panel"], v["panel_2"], darker=True),
        follow(_N, "#7e8894"),
    ),
    Role("line_strong", lambda v: mix(v["muted"], v["surface"], 0.75), follow(_N, "#353c47", lightness=True)),
    # Selected text: a pale fill behind the ordinary ink.
    Role(
        "select",
        lambda v: at_least(mix(v["secondary"], WHITE, 0.35), 0.88),
        follow(Base.PRIMARY, "#1d2540"),
    ),
    # The primary action, focus, checkboxes, sliders, the border of a field being typed in.
    # Moved until its ink reads on it, so a button's text passes the contrast check for any base.
    Role("control", lambda v: fill_behind_ink(at_most(v["primary"], 0.58)), lambda v: fill_behind_ink(v["primary"])),
    # Text on the control color; in the dark set the ground's own dark, which is darker than the usual dark ink.
    Role(
        "control_ink",
        lambda v: ink_on(v["control"]),
        lambda v: WHITE if ink_on(v["control"]) == WHITE else min(v["ground"], DARK_INK, key=luminance),
    ),
    # Selected rows and pressed buttons.
    Role(
        "control_soft",
        lambda v: at_least(mix(v["primary"], v["surface"], 0.09), 0.88),
        follow(Base.PRIMARY, "#1b2236"),
    ),
    # A planned change: amber marks, counts and borders, and the fill behind them.
    Role(
        "change",
        lambda v: readable(at_most(v["accent"], 0.6), v["panel"], v["panel_2"], darker=True),
        lambda v: v["accent"],
    ),
    Role(
        "change_soft",
        lambda v: at_least(mix(v["accent"], v["panel"], 0.18), 0.93),
        follow(Base.ACCENT, "#2b2314"),
    ),
    Role("danger", "#c4302b", "#ff7b72"),
    # A dropped track or a destructive action, and the fill behind it.
    Role("drop", lambda v: v["danger"], "#ff8077"),
    Role("drop_soft", lambda v: mix(v["drop"], v["panel"], 0.12), "#2c1817"),
    # An added file or a program that was found, and the fill behind it.
    Role("add", "#1d7a52", "#62d6a5"),
    Role("add_soft", lambda v: mix(v["add"], v["panel"], 0.12), "#13281f"),
    # A track's flags drawn on its code chip: the default flag colours the code, the forced flag frames it.
    Role(
        "flag_default",
        lambda v: readable(at_most(v["default_track"], 0.55), v["panel_3"], v["panel"], darker=True),
        lambda v: readable(at_least(v["default_track"], 0.72), v["panel_3"], v["panel"], darker=False),
    ),
    Role(
        "flag_forced",
        lambda v: readable(at_most(v["forced_track"], 0.55), v["panel_3"], v["panel"], darker=True),
        lambda v: readable(at_least(v["forced_track"], 0.72), v["panel_3"], v["panel"], darker=False),
    ),
    # Notices and warnings drawn as text.
    Role(
        "accent_ink",
        lambda v: readable(at_most(mix(v["accent"], "#000000", 0.72), 0.565), v["surface"], v["chrome"], darker=True),
        lambda v: readable(at_least(v["accent"], 0.70), v["surface"], v["chrome"], darker=False),
    ),
)

ROLE: dict[str, Role] = {role.key: role for role in ROLES}

# The roles the Qt Quick window draws with; its Theme object exposes exactly these.
QUICK_ROLES: tuple[str, ...] = (
    "ground", "panel", "panel_2", "panel_3", "well", "line", "line_strong", "ink", "muted", "faint",
    "control", "control_ink", "control_soft", "select", "change", "change_soft", "drop", "drop_soft",
    "add", "add_soft", "flag_default", "flag_forced",
)  # fmt: skip


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


# Logical pixels; Qt scales them for the screen. The Qt Quick window reads every entry through its Theme object.
SIZES: dict[str, int] = {
    "text_xs": 11,  # section labels, keys, counts
    "text_sm": 12,  # hints, the status bar, file names
    "text_md": 13,  # everything else
    "text_lg": 15,  # card titles
    "text_xl": 18,  # the inspector's title
    "text_2xl": 22,  # the workspace's title
    "text_3xl": 30,  # the home screen's title
    "row_sm": 24,  # library tree rows, chips
    "row_md": 30,  # buttons, fields, tabs of a side panel
    "row_lg": 36,  # the drop area's buttons, track rows
    "radius_sm": 4,  # chips, counts, scrollbar thumbs
    "radius_md": 7,  # buttons, fields and rows
    "radius_lg": 11,  # panels and cards
    "space_xs": 2,
    "space_sm": 4,
    "space_md": 8,
    "space_lg": 12,
    "space_xl": 16,
    "space_2xl": 24,
    "panel_gap": 6,  # between the window's panels
    "top_bar": 46,
    "status_bar": 26,
    "workspace_tabs": 44,  # the tab row of the workspace and of the side panel
    "drawer_tabs": 40,  # the tab row of the bottom drawer
    "drawer_height": 320,  # the bottom drawer, pulled up
    "inspector_width": 340,  # the side panel beside the workspace
    "panel_min_width": 200,  # the narrowest a resizable panel may get
    "workspace_min_width": 480,
    "search_width": 380,  # the search field in the top bar
    "icon_sm": 13,
    "icon_md": 15,
    "icon_lg": 20,
    "dot": 6,  # a program's or a row's status dot
    "stroke": 1,  # hairlines and borders
    "scroll_thumb": 6,  # the thumb of a scrollbar, across
    "underline": 2,  # the mark under the current tab, the grip of a split handle
    "dash": 4,  # the dashes of a drop area's outline, in strokes
    "handle_length": 40,  # the grip shown on a split handle under the pointer
    "menu_width": 220,
    "tip_width": 320,  # a wrapped tooltip
    "help_chip": 20,  # the ? that opens a help tip
    "help_width": 340,  # a help tip's card
    "artwork_slot": 64,  # a movie's artwork in the workspace header
    "home_card_height": 190,  # the Programs and Recent cards
    "home_art_width": 160,  # the drawing beside the home screen's title
    "home_text_width": 500,
    "swatch_width": 96,
    "dialog_width": 960,  # the Settings window
    "settings_nav_width": 200,  # the Settings window's section list
    "library_width": 272,
    "progress_width": 160,  # the progress bar in the status bar
    "dim_percent": 60,  # how far the loading layer and the dialogs' backdrops hide the workspace, in percent
    "quick_window_width": 1440,  # the Qt Quick window, which needs room for track names beside the workspace
    "quick_window_height": 900,
    "list_row": 46,  # an episode row of Overview, a file row of the track matrix
    "pill": 20,  # a track pill in an episode row, a code badge
    "matrix_label": 150,  # the narrowest the matrix's file names get; Overview, Review and Jobs size their names by it
    "jobs_file": 420,  # the file name that starts each row of the Jobs drawer
    "jobs_phase": 200,  # one step of a Jobs row: its name over its progress line
    "matrix_column": 82,  # a track chip's least width in an Overview row
    "matrix_header": 166,  # the matrix's column headers with their toggles and where their choice comes from
    "track_card": 64,  # a movie's track card
    "settings_width": 920,  # the Settings dialog
    "settings_height": 660,
    "settings_rail_below": 1200,  # a window narrower than this shows the section list as a rail of icons
    "toggle_width": 34,  # an on/off switch
    "palette_width": 560,  # the command palette
    "names_width": 420,  # the list of each file's name for a track, under a chip's ▾
    "names_height": 320,
    "language_dialog_width": 780,  # the language picker
    "rules_dialog_width": 1200,  # the cleanup rule editor
    "rules_dialog_height": 760,
    "rules_set_width": 220,  # its list of rule sets
    "rules_list_width": 300,  # its list of the rules of a set
    "rule_test_height": 220,  # its live test
    "cue_time_width": 96,  # the time of a line in the Lines panel and in the rule test
    "language_list_height": 304,  # its list of languages
    "language_side_height": 120,  # each of its short lists, regions and scripts
    "tracks_min_height": 160,  # the least Overview's tracks box keeps when its separator is dragged up
    "rows_min_height": 120,  # the least Overview's file list keeps when the separator is dragged down
    "separator_step": 24,  # what an arrow key moves Overview's separator
    "track_title_width": 132,  # the codec column of a track row on Overview
    "track_mark_width": 120,  # where a track row's choice comes from, right-aligned before its flags
    "track_files_width": 76,  # the "Files" button at the end of a track row
    "track_row_two_lines_below": 480,  # a track row narrower than this puts its name, count and mark on a second line
    "track_strip_label": 520,  # a track's row beside its strip of files, which stands still as the strip scrolls
    "track_strip_label_narrow": 236,  # its short form: the codec over the first of the mark, the count and the name
    "strip_label_short_below": 640,  # a Tracks place narrower than this takes the short form of the rows
    "strip_pitch": 26,  # one file's width in the strip
    "strip_cell": 18,  # the frame of a cell that differs
    "strip_run": 40,  # the least width of a run of files that follow every track, folded into one
    "window_min_width": 1024,
    "window_min_height": 640,
}

# Compact density: the sizes that change, for long seasons on small screens. Rows and panel headers get shorter;
# text keeps its size.
COMPACT_SIZES: dict[str, int] = {
    "row_lg": 30,
    "list_row": 36,
    "workspace_tabs": 36,
    "drawer_tabs": 34,
    "track_card": 52,
}

# The Qt Quick window bundles its two faces (SIL Open Font License) rather than trying installed ones.
QUICK_FONT = "Inter"
QUICK_MONO = "JetBrains Mono"
