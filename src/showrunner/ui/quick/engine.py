"""Building the QML engine of the window: the `Theme` and `Strings` singletons, the bundled fonts, the icon provider
and the controller, then `Main.qml`. The app, the tests and the screenshot script all build it here."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlError, qmlRegisterSingletonType
from PySide6.QtQuickControls2 import QQuickStyle

from showrunner.ui.quick.icons import IconProvider
from showrunner.ui.quick.strings import Strings
from showrunner.ui.quick.theme import Theme

QML_DIR = Path(__file__).parent / "qml"
FONTS_DIR = Path(__file__).parent / "fonts"
MAIN_QML = QML_DIR / "Main.qml"
MODULE = "Showrunner"

_ready = False


def _singleton[T: QObject](kind: Callable[..., T]) -> Callable[[QQmlEngine], T]:
    # Each engine gets its own object, owned by that engine: a registered instance may serve one engine only.
    return lambda engine: kind(parent=engine)


def prepare() -> None:
    """Once per process, before the first engine: the controls style, the singletons and the fonts."""
    global _ready
    if _ready:
        return
    # Basic draws only what the QML files ask for, without a native look that would ignore the theme.
    QQuickStyle.setStyle("Basic")
    qmlRegisterSingletonType(Theme, MODULE, 1, 0, "Theme", _singleton(Theme))
    qmlRegisterSingletonType(Strings, MODULE, 1, 0, "Strings", _singleton(Strings))
    for font in sorted(FONTS_DIR.rglob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(font)) == -1:
            raise RuntimeError(f"The bundled font {font.name} could not be loaded")
    _ready = True


def build_engine(
    controller: QObject,
    *,
    source: Path = MAIN_QML,
    on_warnings: Callable[[list[QQmlError]], None] | None = None,
) -> QQmlApplicationEngine:
    """An engine with the controller as `app` and `source` loaded; `on_warnings` hears every QML warning."""
    prepare()
    engine = QQmlApplicationEngine()
    if on_warnings is not None:
        engine.warnings.connect(on_warnings)
    engine.addImageProvider("icon", IconProvider())
    engine.rootContext().setContextProperty("app", controller)
    look = getattr(controller, "look", None)
    if look is not None:
        # Before the window loads, so it paints in the chosen look from the first frame.
        engine.singletonInstance(MODULE, "Theme").follow(look)
    engine.load(QUrl.fromLocalFile(str(source)))
    return engine
