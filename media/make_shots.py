r"""Takes the screenshots the media pages show: Overview, Tracks, Names and Review of the real window.

    .venv\Scripts\python.exe media\make_shots.py [folder]

The window opens in the dark theme at 1280x800, far off the visible screen, on the made-up sample library the UI tests
use (two shows and three movies; no file is read), with both programs shown as found and the data folder in a scratch
folder. It is drawn with OpenGL as the app is: Qt's off-screen platform falls back to the software renderer, which
draws dashed frames outside the lists that clip them. A few choices are made on the first
season so each view has changes to show. The images go to media/shots (not kept in the repository), or to `folder`.
"""

import os
import sys
import tempfile
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from PySide6.QtGui import QImage

REPO = Path(__file__).resolve().parent.parent
SIZE = (1280, 800)
PLACES = ("overview", "tracks", "names", "review")

# The sample library and the program statuses come from the UI tests' fixtures module; it needs no pytest run.
_FIXTURES = REPO / "tests" / "ui" / "quick" / "conftest.py"
# Column numbers in that module's sample season: video, audio, subtitles and the paired file.
_COMMENTARY, _TURKISH, _SDH, _FORCED = 3, 2, 4, 7


def _fixtures() -> ModuleType:
    spec = spec_from_file_location("sample_fixtures", _FIXTURES)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blank(image: QImage) -> bool:
    """A grab made before the first frame of a place is drawn comes back as one flat colour."""
    step = 40
    colors = {image.pixel(x, y) for x in range(0, image.width(), step) for y in range(0, image.height(), step)}
    return len(colors) < 8


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "media" / "shots"
    out.mkdir(parents=True, exist_ok=True)
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["SHOWRUNNER_HOME"] = scratch
        return _take(out)


def _take(out: Path) -> int:
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from showrunner.app.profiles import registered  # noqa: F401  # registers every stage's options
    from showrunner.tools.dependencies.detect import State
    from showrunner.ui.quick.engine import build_engine
    from showrunner.ui.quick.window import WindowController

    sample = _fixtures()
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QApplication(sys.argv)
    statuses = sample.program_statuses()
    statuses["ffmpeg"] = replace(statuses["ffmpeg"], state=State.FOUND, path=Path("ffmpeg"), version="7.1")
    controller = WindowController(statuses=lambda: statuses, get_program=lambda spec: None)
    engine = build_engine(controller)
    window = engine.rootObjects()[0]
    window.setPosition(-20000, -20000)
    window.resize(*SIZE)

    def settle() -> None:
        for _ in range(6):
            QTest.qWait(150)
            while controller.planning:
                QTest.qWait(50)

    controller.look.set_mode("dark")
    controller.start()
    while controller.programs[0]["state"] == "checking":
        QTest.qWait(50)
    library = sample.neutral_library()
    controller.model.set_library(library)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season)
    settle()
    controller.toggle_keep(_COMMENTARY)
    controller.toggle_keep(_SDH)
    controller.toggle_flag(_TURKISH, "default")
    controller.toggle_flag(_FORCED, "forced")
    controller.start_template("title_template")
    controller.rail_remove(0)
    controller.rail_append("show")
    controller.rail_append_text(" - ")
    controller.rail_append("episode_title")
    controller.start_template("audio_track_template")
    settle()
    for place in PLACES:
        window.setProperty("place", place)
        settle()
        assert window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.OpenGL
        image = window.grabWindow()
        for _ in range(5):
            if not _blank(image):
                break
            settle()
            image = window.grabWindow()
        assert not _blank(image), place
        assert image.save(str(out / f"{place}.png")), place
    controller.stop_jobs()
    engine.deleteLater()
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
