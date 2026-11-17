"""The editor of a hand-written track rule: its draft and form in Python, and the form in the Rules panel, driven
from the keyboard."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.stages.tracks import (
    FlagShape,
    FlagTest,
    KindTest,
    SourceTest,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
)
from showrunner.ui.quick.rule_editor import Draft, problems
from showrunner.ui.quick.window import WindowController

from .test_choices import COMMENTARY, FORCED, open_season, rules, settle


def tracks(controller: WindowController) -> TracksOptions:
    return controller._tracks()


def write(controller: WindowController, *written: TrackRule) -> None:
    """Rules written by hand, after the choices the batch holds."""
    options = tracks(controller)
    controller._set_tracks(replace(options, rules=[*options.rules, *written]))


def form(controller: WindowController) -> dict[str, Any]:
    return controller.rule_editor.form


# The rule with every field set, so that a round trip shows a field the form does not carry.
FULL = TrackRule(
    enabled=False,
    label="Turkish surround",
    match=TrackMatch(
        kind=KindTest.AUDIO,
        languages=["tur", "pt-BR"],
        codecs=["A_EAC3", "DTS"],
        min_channels=6,
        max_channels=8,
        default=FlagTest.UNSET,
        forced=FlagTest.UNSET,
        hearing_impaired=FlagTest.SET,
        visual_impaired=FlagTest.UNSET,
        commentary=FlagTest.UNSET,
        original=FlagTest.SET,
        name="^main",
        name_is_regex=True,
        source=SourceTest.EMBEDDED,
    ),
    verdict=Verdict.KEEP,
    default=FlagShape.FIRST,
    forced=FlagShape.FIRST,
)


# Adding


def test_a_new_rule_is_written_to_the_working_copy_and_the_plan_follows(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    assert editor.form == {"open": False}
    editor.open_new()
    assert form(controller)["open"]
    assert form(controller)["new"]
    editor.set_kind("subtitle")
    editor.set_text("languages", "tur")
    editor.set_test("forced", "set")
    editor.set_verdict("drop")
    assert tracks(controller).rules == []  # nothing is written before Save
    assert editor.save()
    assert not form(controller)["open"]
    assert rules(controller) == ["Drop subtitles in TUR flagged forced"]
    (rule,) = tracks(controller).rules
    assert (rule.from_choice, rule.enabled) == (False, True)
    assert controller.batches.own(controller._key)  # type: ignore[arg-type]
    settle(controller, qtbot)
    # The live plan, Overview's chips and Review follow like for any choice.
    assert controller.matrix["headers"][FORCED]["state"] == "dropped"
    assert controller.change_text == "18 changes in 9 files"


def test_a_new_rule_goes_last_and_a_choice_made_later_still_leads(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_text("label", "Mine")
    assert editor.save()
    assert [r.from_choice for r in tracks(controller).rules] == [True, False]
    controller.toggle_flag(0, "default")  # a second choice goes ahead of the written rule
    assert [r.from_choice for r in tracks(controller).rules] == [True, True, False]
    assert [r["label"] for r in controller.rules] == ["", "", "Mine"]


# Editing


def test_an_edited_rule_stays_in_its_place_and_keeps_what_the_form_does_not_show(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    write(controller, TrackRule(match=TrackMatch(languages=["tur"])), replace(FULL, verdict=Verdict.PASS))
    editor = controller.rule_editor
    editor.open_rule(1)
    assert form(controller)["title"] == "Edit rule 2"
    editor.set_verdict("drop")
    editor.set_text("label", "Dropped")
    assert editor.save()
    first, second = tracks(controller).rules
    assert first == TrackRule(match=TrackMatch(languages=["tur"]))
    assert (second.label, second.verdict, second.enabled, second.from_choice) == ("Dropped", Verdict.DROP, False, False)
    # A drop takes no flag, so the flag actions went with it.
    assert (second.default, second.forced) == (FlagShape.LEAVE, FlagShape.LEAVE)


def test_every_field_goes_through_the_form_and_back(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    write(controller, FULL)
    editor = controller.rule_editor
    editor.open_rule(0)
    shown = form(controller)
    assert (shown["label"], shown["kind"], shown["languages"], shown["codecs"]) == (
        "Turkish surround",
        "audio",
        "tur, pt-BR",
        "A_EAC3, DTS",
    )
    assert (shown["low"], shown["high"], shown["name"], shown["regex"], shown["source"]) == (
        "6",
        "8",
        "^main",
        True,
        "embedded",
    )
    assert shown["tests"] == {
        "default": "unset",
        "forced": "unset",
        "hearing_impaired": "set",
        "visual_impaired": "unset",
        "commentary": "unset",
        "original": "set",
    }
    assert (shown["verdict"], shown["default"], shown["forced"]) == ("keep", "first", "first")
    # Saved unchanged, the rule is the one that was opened.
    assert editor.save()
    assert tracks(controller).rules == [FULL]


def test_every_field_can_be_set_on_a_new_rule(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_text("label", "Turkish surround")
    editor.set_kind("audio")
    editor.set_text("languages", "tur, pt-BR")
    editor.set_text("codecs", "A_EAC3, DTS")
    editor.set_text("low", "6")
    editor.set_text("high", "8")
    editor.set_text("name", "^main")
    editor.set_regex(True)
    for flag, test in (
        ("default", "unset"),
        ("forced", "unset"),
        ("hearing_impaired", "set"),
        ("visual_impaired", "unset"),
        ("commentary", "unset"),
        ("original", "set"),
    ):
        editor.set_test(flag, test)
    editor.set_source("embedded")
    editor.set_verdict("keep")
    editor.set_action("default", "first")
    editor.set_action("forced", "first")
    assert editor.save()
    assert tracks(controller).rules == [replace(FULL, enabled=True)]


def test_a_rule_a_choice_wrote_is_not_edited_here(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    write(controller, TrackRule(label="Mine"))
    editor = controller.rule_editor
    editor.open_rule(0)
    assert not form(controller)["open"]
    editor.open_rule(1)
    assert form(controller)["open"]
    editor.cancel()
    editor.open_rule(9)
    assert not form(controller)["open"]


def test_cancel_leaves_the_rule_as_it_was(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    write(controller, FULL)
    before = tracks(controller)
    editor = controller.rule_editor
    editor.open_rule(0)
    editor.set_verdict("drop")
    editor.set_text("languages", "xx")
    editor.cancel()
    assert tracks(controller) == before
    assert not form(controller)["open"]
    editor.open_rule(0)
    assert (form(controller)["verdict"], form(controller)["languages"]) == ("keep", "tur, pt-BR")


def test_a_choice_made_while_editing_shifts_the_place_but_not_the_rule(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    write(controller, TrackRule(label="before"), TrackRule(label="edited"))
    editor = controller.rule_editor
    editor.open_rule(1)
    controller.toggle_keep(COMMENTARY)  # inserts a choice ahead of the written rules
    editor.set_text("label", "after")
    assert editor.save()
    assert [r.label for r in tracks(controller).rules] == ["", "before", "after"]


def test_a_rule_deleted_while_editing_is_not_written_back(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    write(controller, TrackRule(label="gone"))
    editor = controller.rule_editor
    editor.open_rule(0)
    controller.remove_rule(0)
    editor.set_text("label", "back")
    assert not editor.save()
    assert tracks(controller).rules == []
    assert not form(controller)["open"]


def test_another_batch_closes_the_editor(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.rule_editor.open_new()
    assert form(controller)["open"]
    controller.select(controller.tree.index_of(str(library.items[-3].file.path)))
    assert not form(controller)["open"]


# Problems


def test_each_problem_shows_on_its_field_and_blocks_saving(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    assert form(controller)["can_save"]
    editor.set_text("languages", "tur, xx, yy")
    assert form(controller)["problems"] == {"languages": ["xx is not a language code.", "yy is not a language code."]}
    assert form(controller)["language_names"] == "Turkish"  # what is missing shows too
    editor.set_text("low", "6")
    editor.set_text("high", "2")
    editor.set_text("name", "(")
    editor.set_regex(True)
    found = form(controller)["problems"]
    assert set(found) == {"languages", "channels", "name"}
    assert found["channels"] == ["The lowest is above the highest, so no track fits."]
    assert found["name"][0].startswith("Not a valid pattern: ")
    assert not form(controller)["can_save"]
    # Whatever the screen shows of the form, the reason Save is off is on it.
    assert form(controller)["note"] == "A field has a problem, marked in red. Fix it to save the rule."
    assert not editor.save()
    assert form(controller)["open"]
    assert tracks(controller).rules == []
    # Fixing a field takes its problem away; the rest stay.
    editor.set_text("languages", "tur")
    assert set(form(controller)["problems"]) == {"channels", "name"}
    editor.set_text("high", "8")
    editor.set_regex(False)
    assert form(controller)["problems"] == {}
    assert editor.save()


def test_a_file_beside_the_video_is_not_offered_for_audio_or_video(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    choices = editor.options
    assert [s["key"] for s in choices["sources"]] == ["any", "embedded"]
    assert [s["key"] for s in choices["sources_with_paired"]] == ["any", "embedded", "paired"]
    editor.open_new()
    offered = {}
    for kind in ("any", "video", "audio", "subtitle"):
        editor.set_kind(kind)
        offered[kind] = form(controller)["paired_offered"]
    assert offered == {"any": True, "video": False, "audio": False, "subtitle": True}
    # Changing to audio or video lets go of a file beside the video, and of nothing else.
    editor.set_kind("subtitle")
    editor.set_source("paired")
    editor.set_text("languages", "tur")
    editor.set_kind("audio")
    assert form(controller)["source"] == "any"
    assert form(controller)["languages"] == "tur"
    assert form(controller)["problems"] == {}


def test_a_stored_rule_for_audio_beside_the_video_shows_its_problem(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    write(controller, TrackRule(match=TrackMatch(kind=KindTest.AUDIO, source=SourceTest.PAIRED)))
    editor = controller.rule_editor
    editor.open_rule(0)
    assert form(controller)["paired_offered"]  # still visible, so that it can be changed
    assert list(form(controller)["problems"]) == ["source"]
    assert not editor.save()
    editor.set_source("any")
    assert not form(controller)["paired_offered"]
    assert editor.save()


def test_channels_belong_to_audio(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_text("low", "6")
    assert form(controller)["channels_shown"]
    editor.set_kind("subtitle")  # a subtitle has no channels, so the test would fit nothing
    assert not form(controller)["channels_shown"]
    assert (form(controller)["low"], form(controller)["high"]) == ("", "")
    editor.set_kind("audio")
    assert form(controller)["channels_shown"]


def test_a_drop_has_no_flag_actions(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_action("default", "first")
    assert form(controller)["flags_shown"]
    editor.set_verdict("drop")
    assert not form(controller)["flags_shown"]
    assert form(controller)["default"] == "leave"
    editor.set_verdict("keep")
    assert (form(controller)["default"], form(controller)["forced"]) == ("leave", "leave")


def test_a_locked_batch_cannot_be_written_to(
    controller: WindowController, library: Library, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_text("label", "Mine")
    monkeypatch.setattr(controller, "_locked_paths", lambda: {i.file.path for i in controller._items})
    controller.batch_changed.emit()
    assert not form(controller)["can_save"]
    assert "being applied" in form(controller)["note"]
    assert not editor.save()
    assert form(controller)["open"]
    assert tracks(controller).rules == []
    monkeypatch.undo()
    controller.batch_changed.emit()
    assert form(controller)["note"] == ""
    assert editor.save()


# What the batch has


def test_languages_and_codecs_are_picked_from_the_batch(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    # The video has no language, so "untagged" comes first.
    assert [p["text"] for p in form(controller)["language_picks"]] == ["untagged", "English", "Turkish"]
    editor.set_kind("audio")
    assert [p["text"] for p in form(controller)["codec_picks"]] == ["Dolby Digital Plus", "Dolby Digital", "AAC"]
    assert [p["text"] for p in form(controller)["language_picks"]] == ["English", "Turkish"]
    editor.toggle_pick("languages", 1)
    assert form(controller)["languages"] == "tr"
    assert [p["on"] for p in form(controller)["language_picks"]] == [False, True]
    editor.set_text("languages", "eng, tur")  # typed with other spellings, the picks still know them
    assert [p["on"] for p in form(controller)["language_picks"]] == [True, True]
    editor.toggle_pick("languages", 1)
    assert form(controller)["languages"] == "eng"
    editor.set_text("codecs", "a_eac3")
    assert form(controller)["codec_picks"][0]["on"]
    editor.toggle_pick("codecs", 0)
    assert form(controller)["codecs"] == ""
    editor.toggle_pick("codecs", 2)
    assert form(controller)["codecs"] == "AAC"
    editor.toggle_pick("codecs", 9)  # no such pick
    assert form(controller)["codecs"] == "AAC"


def test_video_and_paired_files_have_picks_too(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_kind("video")
    assert form(controller)["language_picks"] == [{"value": "und", "text": "untagged", "on": False}]
    assert [p["text"] for p in form(controller)["codec_picks"]] == ["HEVC"]
    editor.set_kind("subtitle")
    assert [p["text"] for p in form(controller)["language_picks"]] == ["English", "Turkish"]
    assert [p["text"] for p in form(controller)["codec_picks"]] == ["SubRip"]


def test_the_form_says_how_many_files_the_rule_fits(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    editor = controller.rule_editor
    editor.open_new()
    editor.set_text("languages", "tur")
    assert form(controller)["fits"] == "fits 9 files"  # Episode Seven has no Turkish track
    editor.set_text("languages", "fra")
    assert form(controller)["fits"] == "fits 0 files"
    assert form(controller)["parts"][-1] == {"text": "FRA", "code": True}


# The label


def test_a_label_shows_on_the_rule_and_beside_what_it_dropped(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    write(controller, TrackRule(label="keep turkish", match=TrackMatch(languages=["tur"]), verdict=Verdict.KEEP))
    assert [r["label"] for r in controller.rules] == ["keep turkish"]
    # Beside what a rule did: the Inspector names the rule that drops a track.
    write(controller, TrackRule(label="no commentary", match=TrackMatch(commentary=FlagTest.SET), verdict=Verdict.DROP))
    settle(controller, qtbot)
    dropped = [t for t in controller.inspector["tracks"] if t["state"] == "dropped"]
    assert [t["by"] for t in dropped] == ["· dropped by no commentary"]


# Draft


def test_a_draft_reads_its_text_and_ignores_what_is_no_count() -> None:
    draft = Draft.new().with_text("languages", " tur ,, eng ").with_text("low", "٣").with_text("high", "12")
    assert draft.match.languages == ["tur", "eng"]
    assert (draft.match.min_channels, draft.match.max_channels) == (0, 12)
    assert (draft.languages, draft.low) == (" tur ,, eng ", "٣")  # the text stays as it was typed
    assert problems(draft) == {}


# From the keyboard


def _focus(window: Any) -> QObject:
    return window.activeFocusItem()


def _texts(root: QQuickItem) -> list[str]:
    found = [str(root.property("text"))] if root.isVisible() and root.property("text") else []
    for child in root.childItems():
        found += _texts(child)
    return found


def _named(root: QQuickItem, name: str) -> list[QQuickItem]:
    found = [root] if root.objectName() == name else []
    for child in root.childItems():
        found += _named(child, name)
    return [i for i in found if i.isVisible()]


def _key(window: Any, key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(window, key, modifier)


def _type(window: Any, text: str) -> None:
    """Lower case letters, spaces and commas, as keys: a window has no `keyClicks`."""
    names = {" ": "Space", ",": "Comma"}
    for char in text:
        _key(window, getattr(Qt.Key, f"Key_{names.get(char, char.upper())}"))


def test_the_editor_opens_and_saves_from_the_keyboard(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setProperty("place", "tracks")
    load()
    root = load.window.contentItem()
    (add,) = _named(root, "addRule")
    add.forceActiveFocus()
    _key(load.window, Qt.Key.Key_Space)
    load()
    assert form(controller)["open"]
    # The first field has the focus; the rest follows with Tab, Left and Right.
    assert _focus(load.window).objectName() == "ruleLabel"
    _type(load.window, "keep turkish")
    assert form(controller)["label"] == "keep turkish"
    _key(load.window, Qt.Key.Key_Tab)  # the kind: Any, Video, Audio, Subtitles
    _key(load.window, Qt.Key.Key_Right)
    _key(load.window, Qt.Key.Key_Right)
    assert form(controller)["kind"] == "audio"
    _key(load.window, Qt.Key.Key_Tab)
    _key(load.window, Qt.Key.Key_Tab)
    assert _focus(load.window).objectName() == "ruleLanguages"
    _type(load.window, "tur, xx")
    load()
    # The problem stands under the field and Save cannot be pressed; Return and Ctrl+Return do not save either.
    assert "xx is not a language code." in _texts(root)
    (save,) = _named(root, "saveRule")
    assert not save.property("enabled")
    _key(load.window, Qt.Key.Key_Return)
    _key(load.window, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert form(controller)["open"]
    assert tracks(controller).rules == []
    _key(load.window, Qt.Key.Key_Backspace)
    _key(load.window, Qt.Key.Key_Backspace)
    _key(load.window, Qt.Key.Key_Backspace)
    _key(load.window, Qt.Key.Key_Backspace)
    assert form(controller)["languages"] == "tur"
    load()
    assert "xx is not a language code." not in _texts(root)
    _key(load.window, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    load()
    assert not form(controller)["open"]
    (rule,) = tracks(controller).rules
    assert (rule.label, rule.match.kind, rule.match.languages) == ("keep turkish", KindTest.AUDIO, ["tur"])
    # The focus went back to the button that opened it, and that rule's pencil opens it again.
    assert _focus(load.window) is add
    (pencil,) = _named(root, "editRule")
    pencil.forceActiveFocus()
    _key(load.window, Qt.Key.Key_Space)
    load()
    assert form(controller)["title"] == "Edit rule 1"
    # Escape cancels whatever was typed.
    _type(load.window, " now")
    assert form(controller)["label"] == "keep turkish now"
    _key(load.window, Qt.Key.Key_Escape)
    load()
    assert not form(controller)["open"]
    assert tracks(controller).rules == [rule]
    assert _focus(load.window) is pencil
    assert qt_warnings() == []
    assert load() == []


def test_a_choice_has_no_pencil_and_a_written_rule_does(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    qtbot.waitUntil(lambda: not controller.planning)
    controller.toggle_keep(COMMENTARY)
    write(controller, TrackRule(label="Mine"))
    load.window.setProperty("place", "tracks")
    load()
    root = load.window.contentItem()
    assert len(_named(root, "editRule")) == 1
    assert len(_named(root, "removeRule")) == 1
    assert qt_warnings() == []
    assert load() == []


def test_the_shortcuts_list_the_key_that_saves_a_rule(controller: WindowController) -> None:
    entries = {entry["text"]: entry["keys"] for entry in controller.settings.shortcuts}
    assert entries["Rules: save the rule being written, from any field"] == ["Ctrl+Return"]


def test_the_pattern_switch_answers_the_keyboard(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setProperty("place", "tracks")
    controller.rule_editor.open_new()
    load()
    root = load.window.contentItem()
    (regex,) = _named(root, "ruleRegex")
    regex.forceActiveFocus()
    _key(load.window, Qt.Key.Key_Space)
    assert form(controller)["regex"]
    assert qt_warnings() == []
    assert load() == []
