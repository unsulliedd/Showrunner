"""Where the main window was when it closed, kept as text in the settings and fitted to the screens of the next
start. Pure functions over plain tuples: the controller reads the screens, QML moves the window."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

type Rect = tuple[int, int, int, int]  # x, y, width, height

# The window counts as on a screen when its top left corner, this large, touches it: enough to grab the title bar.
GRAB_WIDTH = 120
GRAB_HEIGHT = 40


@dataclass(frozen=True, slots=True)
class WindowState:
    rect: Rect  # the window's place while it is not maximized
    maximized: bool = False


def encode(state: WindowState) -> str:
    x, y, width, height = state.rect
    return f"{x},{y},{width},{height},{int(state.maximized)}"


def decode(text: str) -> WindowState | None:
    """The state a saved text holds; None for an empty, damaged or empty-sized one."""
    parts = text.split(",")
    if len(parts) != 5:
        return None
    try:
        x, y, width, height, maximized = (int(p) for p in parts)
    except ValueError:
        return None
    if width <= 0 or height <= 0 or maximized not in (0, 1):
        return None
    return WindowState((x, y, width, height), bool(maximized))


def _overlap(a: Rect, b: Rect) -> int:
    width = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    height = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(width, 0) * max(height, 0)


def fit(state: WindowState, screens: Sequence[Rect]) -> WindowState | None:
    """The state on a screen that exists now (`screens` lists the usable area of each, the primary first).

    The window keeps its place when its title bar touches a screen, moved just far enough to lie inside it; a window
    left on a screen that is gone is centred on the primary one. Its size never exceeds the screen it lands on.
    None when no screen is known.
    """
    if not screens:
        return None
    x, y, width, height = state.rect
    grab = (x, y, min(width, GRAB_WIDTH), min(height, GRAB_HEIGHT))
    target = max(screens, key=lambda s: _overlap(grab, s))
    visible = _overlap(grab, target) > 0
    if not visible:
        target = screens[0]
    left, top, room_w, room_h = target
    width, height = min(width, room_w), min(height, room_h)
    if visible:
        x = min(max(x, left), left + room_w - width)
        y = min(max(y, top), top + room_h - height)
    else:
        x, y = left + (room_w - width) // 2, top + (room_h - height) // 2
    return WindowState((x, y, width, height), state.maximized)
