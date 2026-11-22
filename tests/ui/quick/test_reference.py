"""The Reference row of the Subtitles place, the files that name the reference they work against, and the Lines panel
showing a text track of the video."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.stages.subtitles import Wanted
from showrunner.ui.quick import lines as lines_module
from showrunner.ui.quick.review import unavailable_text
from showrunner.ui.quick.subtitles import unavailable
from showrunner.ui.quick.window import WindowController

from .test_choices import open_season, settle

CUES = [Cue(1, 2, "(DOOR SLAMS)\nWhere were you?"), Cue(3, 4, "Fine.")]


@pytest.fixture(autouse=True)
def videos_under_tmp(library: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sample library's paths are relative, so its videos are real (empty) files under the test's folder: a track
    is read from a video that is there, and its stamp is the file's."""
    monkeypatch.chdir(tmp_path)
    for item in library.items:
        item.file.path.parent.mkdir(parents=True, exist_ok=True)
        item.file.path.write_bytes(b"matroska")


def reference_row(controller: WindowController) -> dict[str, Any]:
    return next(r for r in controller.subtitles["rows"] if r["key"] == "reference")


def test_the_row_offers_the_groups_of_the_batch_and_says_what_automatic_found(
    controller: WindowController, library: Any, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    row = reference_row(controller)
    assert [p["key"] for p in row["pick"]] == ["automatic", "0", "1", "2", "audio"]
    assert [p["text"] for p in row["pick"][1:4]] == [
        "English SubRip (SDH) · 10 files",
        "English SubRip · 10 files",
        "Turkish SubRip (Forced) · 9 files",
    ]
    assert (row["text"], row["fallbacks"]) == ("Automatic", "")
    # English text tracks come first, and the SDH one is the first of them in every file.
    assert row["found"] == "English SubRip (SDH) in 10 files"


def test_a_chosen_group_a_file_lacks_falls_back_and_the_row_names_the_file(
    controller: WindowController, library: Any, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.pick_reference("2")
    settle(controller, qtbot)
    row = reference_row(controller)
    assert row["text"] == "Turkish SubRip (Forced)"
    assert row["found"] == "Turkish SubRip (Forced) in 9 files · English SubRip (SDH) in 07"
    assert row["fallbacks"] == "07 has no Turkish SubRip (Forced): English SubRip (SDH) used"
    assert row["own"] is True
    assert controller.field_marks["subtitles.reference"] == {"from": "", "over": ""}

    controller.pick_reference("audio")
    assert (reference_row(controller)["text"], reference_row(controller)["fallbacks"]) == ("The audio", "")
    controller.pick_reference("automatic")
    assert reference_row(controller)["text"] == "Automatic"


def test_a_file_that_works_against_the_reference_names_it(
    engines: WindowController, library: Any, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    controller.workspace.set_options(
        "subtitles",
        replace(
            controller.workspace.batches.profile(controller.workspace.key).for_stage("subtitles"),
            languages={"de": Wanted.WANTED},
        ),
    )
    settle(controller, qtbot)
    first = controller.subtitles["files"][0]
    assert first["reference"] == "Works against: English SubRip (SDH)"
    assert [(p["code"], p["steps"]) for p in first["plan"]] == [("DEU", "translate")]


@pytest.fixture
def tracks_read(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def read(mkvextract: Path, video: Path, track: Any, language: Language | None, cancel: Any = None) -> list[Cue]:
        asked.append(f"{video.name}:{track.id}")
        return CUES

    monkeypatch.setattr(lines_module, "track_cues", read)
    return asked


def test_the_lines_panel_shows_a_text_track_read_in_the_background(
    controller: WindowController, library: Any, qtbot: QtBot, tracks_read: list[str]
) -> None:
    open_season(controller, library, qtbot)
    controller.focus_file(str(library.items[0].file.path))
    assert [entry["label"] for entry in controller.lines["languages"]] == [
        "TUR",
        "ENG SubRip",
        "ENG SubRip",
        "TUR SubRip",
    ]
    controller.pick_lines_file(1)
    qtbot.waitUntil(lambda: len(controller.lines["rows"]) == 2)
    assert tracks_read == ["Show.Name.S01E01.mkv:4"]
    assert controller.lines["file"] == "English SubRip (SDH)"
    assert controller.lines["summary"].startswith("No cleanup is planned")
    # The lines are kept: showing the track again takes nothing out of the video again.
    controller.pick_lines_file(0)
    controller.pick_lines_file(1)
    assert len(controller.lines["rows"]) == 2
    assert len(tracks_read) == 1


def test_the_rule_editor_tests_against_a_track_once_it_is_read(
    controller: WindowController, library: Any, qtbot: QtBot, tracks_read: list[str]
) -> None:
    open_season(controller, library, qtbot)
    controller.focus_file(str(library.items[0].file.path))
    controller.pick_lines_file(1)
    qtbot.waitUntil(lambda: len(controller.lines["rows"]) == 2)
    loaded = controller.lines_panel.loaded()
    assert loaded is not None
    cues, language, name = loaded
    assert (cues, language, name) == (CUES, Language("eng"), "English SubRip (SDH)")


def test_a_track_that_cannot_be_read_says_so(
    controller: WindowController, library: Any, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> list[Cue]:
        raise ValueError("not a subtitle")

    monkeypatch.setattr(lines_module, "track_cues", fail)
    open_season(controller, library, qtbot)
    controller.focus_file(str(library.items[0].file.path))
    controller.pick_lines_file(1)
    qtbot.waitUntil(lambda: controller.lines["empty"].endswith("could not be read out of the video."))
    assert controller.lines["rows"] == []


def test_review_names_the_reference_a_file_works_against(engines: WindowController, library: Any, qtbot: QtBot) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    controller.workspace.set_options(
        "subtitles",
        replace(
            controller.workspace.batches.profile(controller.workspace.key).for_stage("subtitles"),
            languages={"de": Wanted.WANTED},
        ),
    )
    settle(controller, qtbot)
    detail = controller.review["rows"][0]["detail"]
    assert [line["text"] for line in detail if line["label"] == "Reference"] == ["Works against: English SubRip (SDH)."]


def test_reading_work_whose_program_is_missing_says_which_program() -> None:
    assert unavailable("ocr") == "Reading a picture subtitle needs Tesseract and its language data"
    assert unavailable("reference") == "Reading a subtitle track needs MKVToolNix's mkvextract"
    assert unavailable_text("ocr", 1).startswith(
        "Reading a picture subtitle needs Tesseract and its language data, so 1"
    )
    assert unavailable_text("ocr", 3).startswith(
        "Reading picture subtitles needs Tesseract and its language data, so 3"
    )
    assert unavailable_text("sync", 3).startswith("Sync is not available in this version yet")
