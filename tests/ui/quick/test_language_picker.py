"""The language picker: its lists and the tag as it is built, a chip's badge that opens it, the choice as a rule of the
place that is open, and the Names place that uses it for the tracks without a language."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.languages import use_languages
from showrunner.app.library.library import Library
from showrunner.core.language import add_languages
from showrunner.tools.mkvtoolnix.languages import MkvLanguage
from showrunner.ui.quick.languages import LanguagePicker
from showrunner.ui.quick.tracks import code
from showrunner.ui.quick.window import WindowController

from .test_choices import COMMENTARY, ENGLISH, TURKISH, open_season, rules, settle


@pytest.fixture(autouse=True)
def no_extra_languages() -> Iterator[None]:
    add_languages({})
    yield
    add_languages({})


def rows(model: Any) -> list[dict[str, str]]:
    """What a list model holds, row by row, as QML reads it."""
    return [
        {bytes(name).decode(): str(model.data(model.index(n, 0), role)) for role, name in model.roleNames().items()}
        for n in range(model.rowCount())
    ]


@pytest.fixture
def picker() -> LanguagePicker:
    return LanguagePicker()


def test_the_picker_lists_every_language_in_a_model_a_list_view_reads(picker: LanguagePicker) -> None:
    picker.begin("chip", "Language", "", {"tur"})
    model = picker.language_model
    assert model.rowCount() > 7800
    first = rows(model)[0]
    assert (first["code"], first["name"], first["detail"]) == ("tur", "Turkish", "tur, tr")
    assert model.rowCount(model.index(0, 0)) == 0  # a list has no children


def test_a_search_finds_names_and_codes_and_the_batch_comes_first(picker: LanguagePicker) -> None:
    picker.begin("chip", "Language", "", {"cmn"})
    for text in ("port", "pt", "por"):
        picker.set_query(text)
        assert rows(picker.language_model)[0]["code"] == "por"
    picker.set_query("")
    assert [r["code"] for r in rows(picker.language_model)[:1]] == ["cmn"]
    picker.set_query("zzzzzzzz")
    assert picker.language_model.rowCount() == 0
    assert picker.language_model.row_of("por") == -1


def test_the_tag_is_built_live_from_a_language_a_region_and_a_script(picker: LanguagePicker) -> None:
    picker.begin("chip", "Language of ENG", "", ())
    assert picker.state["tag"] == ""
    assert not picker.state["can_apply"]
    picker.select_language("spa")
    assert (picker.state["tag"], picker.state["name"], picker.state["can_apply"]) == ("es", "Spanish", True)
    picker.select_region("419")
    assert (picker.state["tag"], picker.state["name"]) == ("es-419", "Spanish (Latin America and the Caribbean)")
    picker.select_script("Latn")
    assert picker.state["tag"] == "es-Latn-419"
    # A second click on a region or a script takes it off.
    picker.select_region("419")
    picker.select_script("Latn")
    assert picker.state["tag"] == "es"
    picker.select_language("por")  # another language keeps the rest of the tag
    picker.select_region("BR")
    picker.select_language("spa")
    assert picker.state["tag"] == "es-BR"


def test_the_picker_opens_on_the_tag_it_is_given_and_the_lists_show_where_it_lies(picker: LanguagePicker) -> None:
    picker.begin("chip", "Language", "sr-Latn-RS", ())
    state = picker.state
    assert (state["language"], state["region"], state["script"], state["tag"]) == ("srp", "RS", "Latn", "sr-Latn-RS")
    assert picker.language_model.row_of("srp") >= 0
    assert picker.region_model.row_of("RS") >= 0
    assert picker.script_model.row_of("Latn") >= 0


def test_a_typed_tag_is_checked_as_it_is_typed_and_moves_the_picks(picker: LanguagePicker) -> None:
    picker.begin("chip", "Language", "", ())
    picker.set_typed("es-419")
    state = picker.state
    assert state["check"] == {"state": "ok", "text": "Spanish (Latin America and the Caribbean)"}
    assert (state["language"], state["region"], state["tag"], state["can_apply"]) == ("spa", "419", "es-419", True)
    picker.set_typed("es-4")
    assert picker.state["check"]["state"] == "error"
    assert picker.state["typed"] == "es-4"
    picker.set_typed("")
    assert picker.state["check"]["state"] == "none"
    # A pick after typing clears the field: the tag is the picks.
    picker.set_typed("pt-BR")
    picker.select_region("PT")
    assert (picker.state["typed"], picker.state["tag"]) == ("", "pt-PT")


def test_a_typed_tag_that_is_not_one_cannot_be_applied_but_a_language_mkvtoolnix_lacks_can(
    picker: LanguagePicker,
) -> None:
    known = None
    picker = LanguagePicker(lambda: known)
    picker.begin("chip", "Language", "pt", ())
    picker.set_typed("pt-XX")
    assert picker.state["check"]["state"] == "error"
    # The picks keep the last good tag, which is what Apply would give; the field says the typed one is wrong.
    assert picker.state["tag"] == "pt"
    known = use_languages((MkvLanguage("Portuguese", "por", "por", "pt"),))
    picker.set_typed("tur")
    assert picker.state["check"]["state"] == "warn"
    assert "tur" in picker.state["check"]["text"]
    assert picker.state["can_apply"]  # a warning, not a refusal: Apply is the user's call
    picker.set_typed("pt-BR")
    assert picker.state["check"]["state"] == "ok"


def test_apply_and_clear_answer_with_the_target_and_the_tag(picker: LanguagePicker) -> None:
    answers: list[tuple[str, str]] = []
    picker.applied.connect(lambda target, tag: answers.append((target, tag)))
    picker.begin("chip", "Language", "", ())
    picker.apply()
    assert answers == []  # nothing picked: nothing to give
    picker.set_typed("pt-BR")
    picker.apply()
    picker.clear()
    assert answers == [("chip", "pt-BR"), ("chip", "")]


def test_the_picker_works_without_the_program_and_gains_codes_with_it(picker: LanguagePicker) -> None:
    picker.begin("chip", "Language", "", ())
    assert picker.language_model.row_of("roa") == -1
    use_languages((MkvLanguage("Romance languages", "roa", "roa", ""),))
    picker.refresh_languages()
    assert picker.language_model.row_of("roa") >= 0
    picker.set_typed("roa")
    assert picker.state["check"]["state"] == "ok"
    use_languages(None)
    picker.refresh_languages()
    assert picker.language_model.row_of("roa") == -1


def test_a_badge_with_a_region_reads_the_code_in_capitals_with_it() -> None:
    from showrunner.core.language import Language

    assert code(None) == "UND"
    assert code(Language("por")) == "POR"
    assert code(Language("por", "BR")) == "POR-BR"
    assert code(Language("spa", "419")) == "SPA-419"
    assert code(Language("srp", "RS", "Latn")) == "SRP-LATN-RS"


# A chip's choice


def pick(controller: WindowController, column: int, tag: str) -> None:
    """What the badge does: open the picker for the chip and answer it with `tag`."""
    controller.pick_language(column)
    controller.language_picker.set_typed(tag)
    controller.language_picker.apply()


def test_a_chip_gets_its_language_as_a_rule_that_the_rules_panel_words_and_discard_takes(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    header = controller.matrix["headers"][ENGLISH]
    assert (header["code"], header["language"], header["language_set"]) == ("ENG", "en", "")
    pick(controller, ENGLISH, "pt-BR")
    settle(controller, qtbot)
    header = controller.matrix["headers"][ENGLISH]
    assert (header["code"], header["language"], header["language_set"]) == ("POR-BR", "en", "pt-BR")
    assert rules(controller) == ["Set audio in ENG Dolby Digital Plus 5.1 · language POR-BR"]
    rule = controller.rules[0]
    assert (rule["from_choice"], rule["source"], rule["inherited"]) == (True, "from the matrix", False)
    # The chip's state is still its own: nothing was dropped.
    assert header["state"] == "kept"
    # The plan carries one language change per file that has the track.
    assert controller.change_text == "10 changes in 10 files"
    # A keep or a star on the chip keeps the language.
    controller.toggle_flag(ENGLISH, "default")
    assert controller.matrix["headers"][ENGLISH]["language_set"] == "pt-BR"
    assert "POR-BR" in rules(controller)[0]
    controller.toggle_keep(ENGLISH)
    controller.toggle_keep(ENGLISH)
    assert controller.matrix["headers"][ENGLISH]["language_set"] == "pt-BR"
    # Discard changes takes the choice and the badge reads the language the tracks have again.
    controller.discard_changes()
    settle(controller, qtbot)
    assert controller.rules == []
    assert controller.matrix["headers"][ENGLISH]["code"] == "ENG"


def test_the_picker_opens_on_the_language_a_chip_has_and_leaves_as_it_is_to_clear_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.pick_language(TURKISH)
    state = controller.language_picker.state
    assert (state["tag"], state["clearable"], state["title"]) == ("tr", False, "Language of TUR Dolby Digital Plus 5.1")
    # The batch's languages come first in the list.
    assert {r["code"] for r in rows(controller.language_picker.language_model)[:2]} == {"eng", "tur"}
    pick(controller, TURKISH, "az")
    controller.pick_language(TURKISH)
    assert controller.language_picker.state["tag"] == "az"
    assert controller.language_picker.state["clearable"]
    controller.language_picker.clear()
    assert controller.rules == []
    assert controller.matrix["headers"][TURKISH]["code"] == "TUR"


def test_a_show_s_language_reaches_its_season_marked_and_the_season_overrides_it_and_discards_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    pick(controller, COMMENTARY, "es-419")
    controller.select(season)
    settle(controller, qtbot)
    header = controller.matrix["headers"][COMMENTARY]
    assert (header["code"], header["from"]) == ("SPA-419", "From the show")
    assert [(r["inherited"], r["from"]) for r in controller.rules] == [(True, "From the show")]
    # The picker opens on the show's language; the season's own choice overrides it for itself.
    controller.pick_language(COMMENTARY)
    assert controller.language_picker.state["tag"] == "es-419"
    pick(controller, COMMENTARY, "pt-BR")
    settle(controller, qtbot)
    header = controller.matrix["headers"][COMMENTARY]
    assert (header["code"], header["from"], header["over"]) == ("POR-BR", "", "Overrides the show")
    assert [r["inherited"] for r in controller.rules] == [False]
    # "As it is" in the season: the picker's clear writes a choice of nothing that hides the show's language.
    controller.pick_language(COMMENTARY)
    controller.language_picker.clear()
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["language_set"] == ""
    assert controller.matrix["headers"][COMMENTARY]["code"] == "ENG"
    assert [r["inherited"] for r in controller.rules] == [False]
    assert "as it is" in rules(controller)[0]
    # Discard changes: the season follows the show again.
    controller.discard_changes()
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["code"] == "SPA-419"


def test_a_locked_window_opens_no_picker(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    opened: list[bool] = []
    controller.language_picker.opened.connect(lambda: opened.append(True))
    controller.pick_language(999)
    assert opened == []


# The Names place


def test_the_names_place_uses_the_same_picker_for_the_tracks_that_have_no_language(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert controller.untagged["label"] == "as is"
    controller.pick_untagged_language()
    state = controller.language_picker.state
    assert (state["title"], state["tag"], state["clearable"]) == ("Language for untagged tracks", "", False)
    controller.language_picker.set_typed("pt-BR")
    controller.language_picker.apply()
    assert controller.untagged["value"] == "pt-BR"
    assert controller.untagged["label"] == "Portuguese (Brazil) (pt-BR)"
    # It is the metadata option of the place: the show's value reaches the places that chose none, a season's own
    # value overrides it, "as it is" there is a value too, and Discard takes it.
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    assert controller.untagged["value"] == ""
    controller.pick_untagged_language()
    controller.language_picker.set_typed("es-419")
    controller.language_picker.apply()
    controller.select(season)
    settle(controller, qtbot)
    assert controller.untagged["value"] == "pt-BR"
    controller.pick_untagged_language()
    assert controller.language_picker.state["tag"] == "pt-BR"
    assert controller.language_picker.state["clearable"]
    controller.language_picker.clear()
    assert controller.untagged["value"] == ""
    controller.discard_changes()
    settle(controller, qtbot)
    assert controller.untagged["value"] == "es-419"


# The window


def _items(root: QQuickItem, name: str) -> list[QQuickItem]:
    found = [root] if root.objectName() == name else []
    for child in root.childItems():
        found += _items(child, name)
    return found


def _visible(root: QQuickItem, name: str) -> list[QQuickItem]:
    return [i for i in _items(root, name) if i.isVisible()]


def _click(window: Any, item: QQuickItem) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def test_a_click_on_a_badge_opens_the_dialog_and_choosing_a_language_and_a_region_applies_a_rule(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    settle(controller, qtbot)
    load()
    root = load.window.contentItem()
    chip = _visible(root, f"chip{ENGLISH}")[0]
    badge = _visible(chip, "chipBadge")[0]
    assert badge.property("pickable") is True
    assert badge.property("activeFocusOnTab") is True
    _click(load.window, badge)
    load()
    # The dialog lists the languages in a ListView, so only the rows on screen are made.
    (languages,) = _visible(root, "languageList")
    assert languages.metaObject().className().startswith("QQuickListView")
    assert languages.property("count") > 7800
    assert len(_items(languages, "entryRow")) < 60
    controller.language_picker.select_language("spa")
    controller.language_picker.select_region("419")
    load()
    assert load.run("app.language_picker.state.tag") == "es-419"
    (apply,) = _visible(root, "languageApply")
    assert apply.property("enabled") is True
    _click(load.window, apply)
    settle(controller, qtbot)
    load()
    assert [r["from_choice"] for r in controller.rules] == [True]
    assert controller.matrix["headers"][ENGLISH]["code"] == "SPA-419"
    assert qt_warnings() == []


def test_the_badge_opens_the_picker_from_the_keyboard(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    settle(controller, qtbot)
    load()
    root = load.window.contentItem()
    badge = _visible(_visible(root, f"chip{TURKISH}")[0], "chipBadge")[0]
    opened: list[bool] = []
    controller.language_picker.opened.connect(lambda: opened.append(True))
    badge.forceActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Return)
    load()
    assert opened == [True]
    assert qt_warnings() == []
