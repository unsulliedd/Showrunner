"""The help tips: every topic has its strings, the QML names only known topics, and the "?" opens by click and by
keyboard, closes on Escape or a press outside, and is named for a screen reader."""

from __future__ import annotations

import re
from typing import Any

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.quick.engine import QML_DIR
from showrunner.ui.quick.help import HELP_TOPICS, help_topic
from showrunner.ui.quick.window import WindowController

from .test_choices import open_season
from .test_discard import _evaluate, _visible


@pytest.mark.parametrize("topic", HELP_TOPICS)
def test_every_topic_has_a_title_an_explanation_and_an_example(topic: str) -> None:
    text = help_topic(topic)
    for part in ("title", "explanation", "example"):
        assert text[part]
        assert text[part] != f"help.{topic}.{part}"  # the key itself comes back for a missing string
    assert text["name"] == f"Help: {text['title']}"


@pytest.mark.parametrize("topic", HELP_TOPICS)
def test_no_topic_names_review_s_former_not_this_time_button(topic: str) -> None:
    text = help_topic(topic)
    assert "Not this time" not in text["explanation"] + text["example"]


def test_an_unknown_topic_is_refused() -> None:
    with pytest.raises(KeyError):
        help_topic("nowhere")


def test_the_qml_uses_exactly_the_known_topics() -> None:
    used = {
        topic for path in QML_DIR.glob("*.qml") for topic in re.findall(r'\btopic: "([^"]+)"', path.read_text("utf-8"))
    }
    assert used == set(HELP_TOPICS)


def test_the_examples_name_no_real_show() -> None:
    examples = " ".join(help_topic(topic)["example"] for topic in HELP_TOPICS)
    assert "Show Name (2020)" in examples
    assert tr("help.rules.example") in examples


def _click(window: Any, item: QQuickItem) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def _shown(tip: QObject) -> bool:
    return bool(tip.property("shown"))


def test_the_tip_opens_by_click_and_closes_by_escape_a_second_click_and_a_press_outside(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    load()
    window, root = load.window, load.window.contentItem()
    tip = _visible(root, "excludeTip")
    assert _evaluate(tip, "Accessible.name") == "Help: Exclude"
    QTest.mouseMove(window, tip.mapToScene(QPointF(tip.width() / 2, tip.height() / 2)).toPoint())
    qtbot.wait(300)
    assert not _shown(tip)  # hovering alone does not open it
    _click(window, tip)
    qtbot.waitUntil(lambda: _shown(tip))
    QTest.keyClick(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not _shown(tip))
    _click(window, tip)
    qtbot.waitUntil(lambda: _shown(tip))
    _click(window, tip)  # the button toggles it; a press on it is no "outside"
    qtbot.waitUntil(lambda: not _shown(tip))
    qtbot.wait(100)
    assert not _shown(tip)
    _click(window, tip)
    qtbot.waitUntil(lambda: _shown(tip))
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPointF(40, 880).toPoint())
    qtbot.waitUntil(lambda: not _shown(tip))


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_the_tip_opens_by_keyboard_and_gives_the_focus_back_on_escape(
    key: Qt.Key, load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    load()
    window = load.window
    tip = _visible(window.contentItem(), "excludeTip")
    tip.forceActiveFocus()
    assert tip.property("activeFocus")
    QTest.keyClick(window, key)
    qtbot.waitUntil(lambda: _shown(tip))
    QTest.keyClick(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not _shown(tip))
    assert tip.property("activeFocus")


def test_each_place_shows_its_tips_named_for_a_reader(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    load()
    window, root = load.window, load.window.contentItem()
    names = {"excludeTip": "Help: Exclude"}
    window.setProperty("place", "tracks")
    names |= {"rulesTip": "Help: Track rules", "firstKeptTip": "Help: First kept"}
    for object_name, name in names.items():
        assert _evaluate(_visible(root, object_name), "Accessible.name") == name
    window.setProperty("place", "review")
    assert _evaluate(_visible(root, "discardTip"), "Accessible.name") == "Help: Discard changes"
    controller.add_token()
    controller.rename_token(0, "code")
    window.setProperty("place", "names")
    qtbot.wait(100)
    assert _evaluate(_visible(root, "replaceValuesTip"), "Accessible.name") == "Help: Replace values"
    assert _evaluate(_visible(root, "tokensTip"), "Accessible.name") == "Help: Separators between tokens"
    assert load() == []
