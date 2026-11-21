r"""Makes the app icon files from media/icon.svg.

    .venv\Scripts\python.exe media\make_icons.py

Qt draws the SVG on a transparent background at each size the icon holds, so the small sizes are drawn for their size
rather than shrunk from the large one, and Pillow packs them into src/showrunner/ui/resources/icon.ico. Pillow is
needed only to run this script and is not a dependency of the app. The SVG itself is copied there too, for the header.
"""

import io
import shutil
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

MEDIA = Path(__file__).resolve().parent
RESOURCES = MEDIA.parent / "src" / "showrunner" / "ui" / "resources"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(renderer: QSvgRenderer, size: int) -> Image.Image:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841  # QImage and QPainter need an application object
    renderer = QSvgRenderer(str(MEDIA / "icon.svg"))
    images = [draw(renderer, size) for size in SIZES]
    largest = images[-1]
    for image in images:
        # Every size must fill its frame; a drawing cut short shows as half an icon on the taskbar.
        assert image.getbbox() == (0, 0, image.width, image.height), image.size
    RESOURCES.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MEDIA / "icon.svg", RESOURCES / "icon.svg")
    largest.save(RESOURCES / "icon.ico", sizes=[(s, s) for s in SIZES], append_images=images[:-1])


if __name__ == "__main__":
    main()
