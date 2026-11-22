"""The Cleanup row of the Subtitles place with its live counts, the Lines panel that marks what cleanup does to the
selected file, and the rule editor with its test."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from showrunner.app.rules import RuleStore as Store
from showrunner.core.cue import Cue, write_cues
from showrunner.core.language import Language
from showrunner.core.media import Episode
from showrunner.stages.subtitles import RuleSetUse, SubtitlesOptions
from showrunner.stages.tracks import PairedFile, TracksOptions
from showrunner.tools.cleanit import RuleDef, RuleKind, RuleSet
from showrunner.ui.quick.cleanup_editor import CleanupEditor
from showrunner.ui.quick.window import WindowController

from .test_choices import open_season, settle

CUES = [
    Cue(1, 2, "(DOOR SLAMS)\nWhere were you?"),
    Cue(3, 4, "Visit opensubtitles.org"),
    Cue(5, 6, "Fine."),
]


@pytest.fixture(autouse=True)
def files_under_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sample library's paths are relative, so its Turkish files are real ones under the test's folder."""
    monkeypatch.chdir(tmp_path)


def season_with_files(controller: WindowController, library: Any, qtbot: QtBot, tmp_path: Path) -> None:
    items = [
        i
        for i in library.items
        if isinstance(i.identity, Episode) and (i.identity.season, i.identity.show) == (1, "Show Name")
    ]
    for item in items:
        for subtitle in item.subtitles:
            path = tmp_path / subtitle.path
            path.parent.mkdir(parents=True, exist_ok=True)
            write_cues(path, CUES)
    open_season(controller, library, qtbot)
    chosen = TracksOptions(add_paired=[PairedFile.of(items[0].subtitles[0])])
    controller.workspace.set_options("tracks", chosen)
    controller.workspace.set_options(
        "subtitles",
        SubtitlesOptions(cleanup={"no-sdh": RuleSetUse.USED, "no-spam": RuleSetUse.USED, "gone": RuleSetUse.USED}),
    )
    settle(controller, qtbot)


def cleanup_row(controller: WindowController) -> dict[str, Any]:
    return next(r for r in controller.subtitles["rows"] if r["key"] == "cleanup")


def test_the_cleanup_row_names_each_set_and_what_it_covers_and_counts_what_it_does(
    controller: WindowController, library: Any, qtbot: QtBot, tmp_path: Path
) -> None:
    season_with_files(controller, library, qtbot, tmp_path)
    row = cleanup_row(controller)
    sdh, spam, gone = row["items"]
    assert (sdh["name"], sdh["languages"], sdh["missing"]) == ("Hearing impaired", "any language", False)
    assert (spam["name"], gone["missing"]) == ("Ads and credits", True)  # a set that is not there cleans nothing
    # Sets already chosen are not offered again; the others of cleanit's, and the user's own, are.
    assert [a["key"] for a in row["add"]] == ["no-lyrics", "no-style", "tidy"]
    # The count is read in the background, from the files as they are.
    qtbot.waitUntil(lambda: cleanup_row(controller).get("count", "") != "")
    assert cleanup_row(controller)["count"] == "Drops 10 lines and changes 10 lines in 10 files"


def test_a_rule_set_is_added_and_the_editor_is_asked_for(
    controller: WindowController, library: Any, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    asked: list[str] = []
    controller.subtitle_settings.editor_asked.connect(asked.append)
    controller.add_rule_set("tidy")
    assert [i["key"] for i in cleanup_row(controller)["items"]] == ["tidy"]
    controller.edit_rule_sets("tidy")
    assert asked == ["tidy"]


def test_the_lines_panel_marks_dropped_and_changed_lines_with_the_rule_that_did_it(
    controller: WindowController, library: Any, qtbot: QtBot, tmp_path: Path
) -> None:
    season_with_files(controller, library, qtbot, tmp_path)
    controller.focus_file(str(library.items[0].file.path))
    view = controller.lines
    assert view["file"].endswith(".tur.srt")
    assert view["sets"] == "Hearing impaired, Ads and credits"
    rows = view["rows"]
    assert [r["state"] for r in rows] == ["changed", "dropped", "kept"]
    assert (rows[0]["after"], rows[0]["rule"]) == ("Where were you?", "drop-brackets-lines")
    assert rows[1]["rule"] == "drop-ads-and-credits"
    assert view["summary"] == "Drops 1 line and changes 1 line"


def test_a_subtitle_nothing_cleans_is_shown_as_it_is(
    controller: WindowController, library: Any, qtbot: QtBot, tmp_path: Path
) -> None:
    season_with_files(controller, library, qtbot, tmp_path)
    controller.workspace.set_options("subtitles", SubtitlesOptions())
    settle(controller, qtbot)
    controller.focus_file(str(library.items[0].file.path))
    assert {r["state"] for r in controller.lines["rows"]} == {"kept"}
    assert controller.lines["summary"].startswith("No cleanup is planned")


def test_a_subtitle_tracks_do_not_add_says_why_nothing_cleans_it(
    controller: WindowController, library: Any, qtbot: QtBot, tmp_path: Path
) -> None:
    season_with_files(controller, library, qtbot, tmp_path)
    controller.workspace.set_options("tracks", TracksOptions())
    settle(controller, qtbot)
    controller.focus_file(str(library.items[0].file.path))
    assert controller.lines["summary"].startswith("This subtitle lies beside the video, but Tracks does not add it")


@pytest.fixture
def editor(tmp_path: Path) -> CleanupEditor:
    store = Store(lambda: tmp_path / "rules")
    return CleanupEditor(lambda: None, lambda: False, rules=store)


def test_a_built_in_set_is_read_only_but_a_rule_can_be_paused_and_the_set_duplicated(editor: CleanupEditor) -> None:
    editor.open("no-sdh")
    assert editor.view["set"]["readonly"] is True
    name = editor.view["set"]["rules"][0]["name"]
    saved: list[int] = []
    editor.saved.connect(lambda: saved.append(1))
    editor.set_field("name", "renamed")  # ignored: the set cannot be edited
    assert editor.view["rule"]["name"] == name
    editor.toggle_pause(0)
    assert [r["paused"] for r in editor.view["set"]["rules"]][:2] == [True, False]
    assert saved == [1]
    assert editor.duplicate_set("no-sdh") != ""  # a built-in name is taken
    assert editor.duplicate_set("mine") == ""
    assert editor.view["set"]["builtin"] is False
    editor.set_field("name", "renamed")
    assert editor.view["rule"]["name"] == "renamed"
    assert editor.view["set"]["rules"][0]["paused"] is True  # the copy is of the set as it was shown


def test_an_own_set_is_written_on_every_valid_change_and_a_broken_pattern_is_held_back(
    editor: CleanupEditor, tmp_path: Path
) -> None:
    assert editor.new_set("mine") == ""
    assert editor.new_set("mine") != ""  # it exists
    assert editor.new_set("a b") != ""  # no spaces
    file = tmp_path / "rules" / "cleanit-mine.yml"
    assert file.is_file()
    editor.set_field("patterns", "foo")
    editor.set_field("replacement", "bar")
    editor.toggle_pause(0)
    assert "foo" in file.read_text(encoding="utf-8")
    assert editor.view["set"]["error"] == ""
    editor.set_field("kind", "regex")
    before = file.read_text(encoding="utf-8")
    editor.set_field("patterns", "(")
    assert editor.view["set"]["error"] != ""
    assert file.read_text(encoding="utf-8") == before  # the broken pattern is not written
    editor.set_field("patterns", "fo+")
    assert editor.view["set"]["error"] == ""
    assert "fo+" in file.read_text(encoding="utf-8")


def test_rules_are_added_moved_and_removed_and_the_order_is_written_as_priorities(
    editor: CleanupEditor, tmp_path: Path
) -> None:
    editor.new_set("mine")
    editor.add_rule()
    editor.set_field("name", "second")
    assert [r["name"] for r in editor.view["set"]["rules"]] == ["New rule", "second"]
    editor.move_rule(1, -1)
    assert [r["name"] for r in editor.view["set"]["rules"]] == ["second", "New rule"]
    text = (tmp_path / "rules" / "cleanit-mine.yml").read_text(encoding="utf-8")
    assert text.index("second") < text.index("New rule")
    editor.remove_rule(0)
    editor.remove_rule(0)  # the last rule stays: a set file holds at least one
    assert len(editor.view["set"]["rules"]) == 1
    editor.delete_set()
    assert not (tmp_path / "rules" / "cleanit-mine.yml").exists()


def test_the_test_runs_the_whole_set_on_the_sample_and_says_what_the_rule_did(
    editor: CleanupEditor, tmp_path: Path
) -> None:
    store = Store(lambda: tmp_path / "rules")
    store.save(
        RuleSet(
            "mine",
            (
                RuleDef("first", ("cat",), RuleKind.TEXT, replacement="dog", priority=5),
                RuleDef("ads", ("sub.example",), RuleKind.TEXT),
            ),
        )
    )
    editor = CleanupEditor(lambda: None, lambda: False, rules=store)
    editor.open("mine")
    editor.set_sample("a cat\n\nvisit sub.example\n\nnothing")
    test = editor.view["test"]
    assert [r["state"] for r in test["rows"]] == ["changed", "dropped", "kept"]
    assert test["summary"] == "This rule changes 1 line and drops 0 lines in the sample"
    editor.set_only_mine(True)
    assert len(editor.view["test"]["rows"]) == 1
    editor.select_rule(1)  # a rule seeds the sample with its own examples
    editor.set_sample("a cat\n\nvisit sub.example\n\nnothing")
    assert editor.view["test"]["summary"] == "This rule changes 0 lines and drops 1 line in the sample"


def test_a_subtitle_of_the_batch_is_the_test_text(tmp_path: Path) -> None:
    store = Store(lambda: tmp_path / "rules")
    editor = CleanupEditor(lambda: (CUES, Language("eng"), "Episode.tur.srt"), lambda: False, rules=store)
    editor.open("no-spam")
    editor.set_source("subtitle")
    test = editor.view["test"]
    assert [r["state"] for r in test["rows"]][:3] == ["kept", "dropped", "kept"] or "dropped" in {
        r["state"] for r in test["rows"]
    }
    assert test["summary"].endswith("in Episode.tur.srt")


def test_nothing_is_written_while_a_job_runs(tmp_path: Path) -> None:
    locked = {"on": False}
    editor = CleanupEditor(lambda: None, lambda: locked["on"], rules=Store(lambda: tmp_path / "rules"))
    editor.new_set("mine")
    locked["on"] = True
    editor.set_field("patterns", "changed")
    assert editor.new_set("other") != ""
    assert "changed" not in (tmp_path / "rules" / "cleanit-mine.yml").read_text(encoding="utf-8")
    assert editor.view["locked"] is True


def test_a_subtitle_edit_file_is_previewed_then_made_into_sets(tmp_path: Path) -> None:
    source = tmp_path / "multiple.xml"
    source.write_text(
        "<Settings><MultipleSearchAndReplaceGroups><Group><Name>Mine</Name><Enabled>true</Enabled>"
        "<Rule><Enabled>true</Enabled><FindWhat>colour</FindWhat><ReplaceWith>color</ReplaceWith>"
        "<SearchType>Normal</SearchType></Rule>"
        "<Rule><Enabled>true</Enabled><FindWhat>\\p{L}</FindWhat><ReplaceWith>x</ReplaceWith>"
        "<SearchType>RegularExpression</SearchType></Rule>"
        "</Group></MultipleSearchAndReplaceGroups></Settings>",
        encoding="utf-8",
    )
    store = Store(lambda: tmp_path / "rules")
    editor = CleanupEditor(lambda: None, lambda: False, rules=store)
    editor.read_import(source)
    shown = editor.view["preview"]
    assert [s["name"] for s in shown["sets"]] == ["Mine"]
    assert shown["skipped_count"] == 1
    assert "Python does not read" in shown["skipped"][0]["reason"]
    assert "Mine" not in store.book().sets  # nothing is written before it is confirmed
    editor.confirm_import()
    assert "Mine" in store.book().sets
    assert editor.view["preview"] == {}
    editor.read_import(tmp_path / "missing.xml")
    assert editor.view["import_error"] != ""
    editor.cancel_import()
    assert editor.view["import_error"] == ""


def test_editing_the_rules_makes_the_plans_again(controller: WindowController, library: Any, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    before = controller.workspace.rules_revision
    controller.cleanup_editor.saved.emit()
    assert controller.workspace.rules_revision == before + 1
    settle(controller, qtbot)


def test_the_dialog_and_the_lines_panel_draw_without_warnings(
    load: Any, controller: WindowController, library: Any, qt_warnings: Any, qtbot: QtBot, tmp_path: Path
) -> None:
    load()
    season_with_files(controller, library, qtbot, tmp_path)
    controller.focus_file(str(library.items[0].file.path))
    load.window.setProperty("place", "subtitles")
    assert load() == []
    controller.cleanup_editor.open("no-sdh")
    assert load() == []
    controller.cleanup_editor.set_source("subtitle")
    controller.cleanup_editor.set_show_yaml(True)
    assert load() == []
    controller.cleanup_editor.set_show_yaml(False)
    controller.cleanup_editor.duplicate_set("mine")
    controller.cleanup_editor.set_field("patterns", "(")
    assert load() == []
    assert qt_warnings() == []


def test_a_set_name_that_differs_only_in_case_is_taken(editor: CleanupEditor) -> None:
    assert editor.new_set("mine") == ""
    assert editor.new_set("MINE") != ""
    assert editor.new_set("TIDY") != ""
