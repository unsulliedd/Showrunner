"""Theme files: the user's color changes as JSON. The current theme lives in the data folder in the same
format that import and export use. A file is only ever read as data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from showrunner.app.storage.files import write_json_atomic
from showrunner.core.options.serialization import Loaded, LoadWarning, WarningKind
from showrunner.ui.theme.color import parse_hex
from showrunner.ui.theme.tokens import ROLE, Base, ColorSet, ThemeColors, with_base, with_role

THEME_FORMAT = 1
THEME_EXTENSION = ".showrunner-theme.json"
FORMAT_KEY = "showrunner_theme"
MAX_THEME_BYTES = 64 * 1024
# Roles that earlier versions wrote and that no longer exist; skipped on load so old files load without warnings.
_RETIRED_ROLES = frozenset(
    {
        "control_fill",
        "chrome_2",
        "control_soft_ink",
        "danger_soft",
        "tip",
        "tip_ink",
        "scroll_thumb",
        "scroll_thumb_hover",
        "focus",
        "link",
        "video",
    }
)


def theme_to_json(colors: ThemeColors) -> dict[str, Any]:
    return {
        FORMAT_KEY: THEME_FORMAT,
        "base": {base.value: hex_color for base, hex_color in colors.base.items()},
        ColorSet.LIGHT.value: dict(colors.light),
        ColorSet.DARK.value: dict(colors.dark),
    }


def save_theme_file(path: Path, colors: ThemeColors) -> None:
    write_json_atomic(path, theme_to_json(colors))


def _unreadable(path: Path) -> Loaded[ThemeColors]:
    return Loaded(ThemeColors(), [LoadWarning(WarningKind.UNREADABLE, str(path))])


def load_theme_file(path: Path) -> Loaded[ThemeColors]:
    """A missing file gives no changes silently. A file that is not a theme gives no changes and an
    `UNREADABLE` warning. Otherwise every valid color is kept and every bad entry is skipped with a warning;
    colors equal to their default are dropped, so what is kept stays sparse."""
    if not path.is_file():
        return Loaded(ThemeColors())
    try:
        if path.stat().st_size > MAX_THEME_BYTES:
            return _unreadable(path)
        # utf-8-sig accepts the byte order mark some Windows editors write.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return _unreadable(path)
    if not isinstance(data, dict) or FORMAT_KEY not in data:
        return _unreadable(path)
    warnings: list[LoadWarning] = []
    version = data.pop(FORMAT_KEY)
    if isinstance(version, int) and not isinstance(version, bool) and version > THEME_FORMAT:
        warnings.append(LoadWarning(WarningKind.NEWER_FORMAT, FORMAT_KEY))
    colors = ThemeColors()
    for section, entries in data.items():
        if section not in ("base", *ColorSet):
            warnings.append(LoadWarning(WarningKind.UNKNOWN_KEY, section))
            continue
        if not isinstance(entries, dict):
            warnings.append(LoadWarning(WarningKind.WRONG_TYPE, section))
            continue
        for key, raw in entries.items():
            if section != "base" and key in _RETIRED_ROLES:
                continue
            location = f"{section}.{key}"
            known = key in Base if section == "base" else key in ROLE
            if not known:
                warnings.append(LoadWarning(WarningKind.UNKNOWN_KEY, location))
                continue
            hex_color = parse_hex(raw) if isinstance(raw, str) else None
            if hex_color is None:
                warnings.append(LoadWarning(WarningKind.WRONG_TYPE, location))
            elif section == "base":
                colors = with_base(colors, Base(key), hex_color)
            else:
                colors = with_role(colors, ColorSet(section), key, hex_color)
    return Loaded(colors, warnings)
