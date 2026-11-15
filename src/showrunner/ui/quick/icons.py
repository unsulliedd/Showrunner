"""Stroked line icons on a 24 px grid, drawn for QML by an image provider in any theme color.

QML asks for `image://icon/<name>/<rrggbb>`; the logo takes two colors, `image://icon/logo/<ink>/<mark>`.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

STROKE_WIDTH = 1.7

ICONS: dict[str, str] = {
    "folder": (
        '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 '
        '1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>'
    ),
    "film": (
        '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7.5 4v16M16.5 4v16M3 '
        '9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"/>'
    ),
    "tv": '<rect x="3" y="6.5" width="18" height="12.5" rx="2.5"/><path d="M8.5 3l3.5 3.5L15.5 3"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    "down": '<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',
    "right": '<path d="M9.5 6.5l5.5 5.5-5.5 5.5"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "sliders": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "audio": '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 10.5v3"/>',
    "subs": '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M7 14.5h4M13 14.5h4M7 11h2M11 11h6"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "resume": '<path d="M19.5 12A7.5 7.5 0 1 1 17.3 6.7"/><path d="M19.5 4v4h-4"/>',
    "names": '<path d="M4 7h10M4 12h7M4 17h9"/><path d="M15.5 13.5l4-4 1.5 1.5-4 4H15.5z"/>',
    "arrow": '<path d="M5 12h14M13.5 6.5L19 12l-5.5 5.5"/>',
    "chapters": '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />',
    "panel_bottom": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 14h18"/>',
    "image": (
        '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="9.5" '
        'r="1.8"/><path d="M3.5 17l5-5 4 4 3-3 5 5"/>'
    ),
    "upload": '<path d="M12 15.5V4M7.5 8.5L12 4l4.5 4.5M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "list": '<path d="M8 7h12M8 12h12M8 17h12M4 7h.01M4 12h.01M4 17h.01"/>',
    "terminal": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15h4.5"/>',
    "eye": (
        '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle '
        'cx="12" cy="12" r="2.8"/>'
    ),
}  # fmt: skip


def icon_svg(name: str, color: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="{STROKE_WIDTH}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'
    )


def logo_svg(ink: str, mark: str) -> str:
    # A clapper frame whose top bar is the one control-colored mark in the chrome.
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<rect x="2.5" y="8" width="19" height="13" rx="3" fill="none" stroke="{ink}" stroke-width="1.8"/>'
        f'<path d="M3.2 6.6l17-3.4.5 2.6-17 3.4z" fill="{mark}"/>'
        f'<path d="M10 11.5v6l5-3z" fill="{ink}"/></svg>'
    )


def svg_for(image_id: str) -> str | None:
    """The SVG for a provider id, or None for an unknown name or a malformed color."""
    name, *colors = image_id.split("/")
    if not colors or not all(len(c) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in c) for c in colors):
        return None
    hexes = [f"#{c}" for c in colors]
    if name == "logo" and len(hexes) == 2:
        return logo_svg(*hexes)
    return icon_svg(name, hexes[0]) if name in ICONS and len(hexes) == 1 else None


class IconProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, image_id: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802  # Qt's name
        side = max(requested.width(), requested.height(), 24)
        image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        svg = svg_for(image_id)
        if svg is not None:
            painter = QPainter(image)
            QSvgRenderer(QByteArray(svg.encode())).render(painter)
            painter.end()
        size.setWidth(side)
        size.setHeight(side)
        return image
