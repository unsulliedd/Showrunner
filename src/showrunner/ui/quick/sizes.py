"""What the user sized in the window, kept in the settings for the next start: the window's place, the split panels,
the height of Overview's tracks box and which files the Tracks strip shows."""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QGuiApplication

from showrunner.app.settings.app_settings import load_settings, save_settings
from showrunner.ui.quick.window_state import Rect, WindowState, decode, encode, fit

_log = logging.getLogger(__name__)


def available_screens() -> list[Rect]:
    """The usable area of every connected screen, the primary one first."""
    return [(r.x(), r.y(), r.width(), r.height()) for r in (s.availableGeometry() for s in QGuiApplication.screens())]


class Sizes:
    """A plain object: it neither emits nor receives signals, and reads and writes the settings when asked."""

    def __init__(self, screens: Callable[[], Sequence[Rect]] = available_screens) -> None:
        self._screens = screens

    def window_state(self) -> dict[str, Any]:
        """Where the window was when it last closed, moved onto a screen that exists now; empty when it was never
        saved or no screen is known."""
        saved = decode(load_settings().value.window_geometry)
        fitted = fit(saved, self._screens()) if saved is not None else None
        if fitted is None:
            return {}
        x, y, width, height = fitted.rect
        return {"x": x, "y": y, "width": width, "height": height, "maximized": fitted.maximized}

    def save_window_state(self, x: int, y: int, width: int, height: int, maximized: bool) -> None:
        text = encode(WindowState((x, y, width, height), maximized))
        settings = load_settings().value
        if text == settings.window_geometry:
            return
        try:
            save_settings(replace(settings, window_geometry=text))
        except OSError:
            _log.exception("Could not save the window's place")

    def overview_tracks_height(self) -> int:
        """The height the user gave Overview's tracks box, 0 when none."""
        return load_settings().value.overview_tracks_height

    def save_overview_tracks_height(self, height: int) -> None:
        settings = load_settings().value
        if height == settings.overview_tracks_height:
            return
        try:
            save_settings(replace(settings, overview_tracks_height=height))
        except OSError:
            _log.exception("Could not save the height of the tracks box")

    def matrix_files(self) -> str:
        """Which files the Tracks strip shows, as the user last chose: `all`, `differ`, or empty for none chosen."""
        return load_settings().value.matrix_files

    def save_matrix_files(self, files: str) -> None:
        settings = load_settings().value
        if files == settings.matrix_files or files not in ("all", "differ"):
            return
        try:
            save_settings(replace(settings, matrix_files=files))
        except OSError:
            _log.exception("Could not save which files the track strip shows")

    def panel_state(self, name: str) -> QByteArray:
        saved = load_settings().value.panel_sizes.get(name, "")
        try:
            return QByteArray(base64.b64decode(saved, validate=True))
        except (binascii.Error, ValueError):
            return QByteArray()

    def save_panel_state(self, name: str, state: QByteArray) -> None:
        settings = load_settings().value
        sizes = {**settings.panel_sizes, name: base64.b64encode(bytes(state.data())).decode("ascii")}
        if sizes == settings.panel_sizes:
            return
        try:
            save_settings(replace(settings, panel_sizes=sizes))
        except OSError:
            _log.exception("Could not save the panel sizes")
