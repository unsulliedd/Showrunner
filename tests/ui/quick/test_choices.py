"""Choices made on Overview and Tracks: live plans in the background, ordinary rules in the batch's working copy,
saved to the workspace file as they are made."""

from __future__ import annotations

import json

from PySide6.QtCore import QModelIndex
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.app.storage.paths import workspace_path
from showrunner.stages.tracks import Verdict
from showrunner.ui.quick.library import PLANNED
from showrunner.ui.quick.window import WindowController

ENGLISH, TURKISH, COMMENTARY, STEREO, SDH, ENGLISH_SUBS, FORCED, SRT = range(8)


def open_season(controller: WindowController, library: Library, qtbot: QtBot, episode: int = 2) -> None:
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[episode].file.path)))
    settle(controller, qtbot)


def settle(controller: WindowController, qtbot: QtBot) -> None:
    qtbot.waitUntil(lambda: not controller.planning)


def rules(controller: WindowController) -> list[str]:
    return [" ".join(str(p["text"]) for p in rule["parts"]) for rule in controller.rules]


def test_a_batch_without_choices_plans_nothing(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    assert controller.change_count == 0
    assert controller.change_text == "Nothing to change yet"
    assert controller.rules == []
    assert [h["state"] for h in controller.matrix["headers"]][:3] == ["kept", "kept", "kept"]


def test_a_chip_click_becomes_a_rule_and_the_plan_follows(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    # The choice shows at once as a rule; the counts wait for the plan.
    assert rules(controller) == ["Drop audio in ENG named Commentary"]
    assert controller.profile_edited
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["state"] == "dropped"
    assert controller.change_text == "10 changes in 10 files"
    tabs = {tab["key"]: tab["count"] for tab in controller.workspace_tabs}
    assert (tabs["tracks"], tabs["names"], tabs["review"]) == (10, 0, 10)
    # The rule is an ordinary one in the batch's working copy.
    assert controller._key is not None
    (rule,) = controller.batches.profile(controller._key).for_stage("tracks").rules
    assert (rule.verdict, rule.from_choice) == (Verdict.DROP, True)
    # A second click keeps the track again and the rule goes.
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    assert controller.rules == []
    assert controller.change_count == 0


def test_stars_write_a_default_and_its_fallback(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot, episode=6)
    controller.toggle_flag(TURKISH, "default")
    controller.toggle_flag(ENGLISH, "default")
    settle(controller, qtbot)
    assert rules(controller) == [
        "Keep audio in TUR named Turkish · default",
        "Keep audio in ENG named English · default if none above",
    ]
    seventh = controller.overview["rows"][6]
    assert seventh["warning"] == "No Turkish audio: English audio becomes the default"
    # Turning the star off again leaves no rule behind: the keep only carried the flag.
    controller.toggle_flag(TURKISH, "default")
    assert rules(controller) == ["Keep audio in ENG named English · default"]


def test_a_paired_file_is_added_and_restored(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_flag(SRT, "default")  # a star on a paired file adds it
    settle(controller, qtbot)
    assert controller.matrix["headers"][SRT]["state"] == "added"
    assert controller.overview["rows"][0]["subtitles"][-1]["added"]
    controller.restore(SRT)
    settle(controller, qtbot)
    assert controller.matrix["headers"][SRT]["state"] == "paired"
    assert controller.rules == []


def test_rules_move_and_pause(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    controller.toggle_keep(SDH)
    controller.move_rule(1, 0)
    assert rules(controller) == ["Drop subtitles in ENG named SDH", "Drop audio in ENG named Commentary"]
    controller.pause_rule(0, True)
    settle(controller, qtbot)
    assert controller.rules[0]["enabled"] is False
    assert controller.matrix["headers"][SDH]["state"] == "kept"
    controller.move_rule(5, 0)  # out of range: nothing moves
    assert len(controller.rules) == 2


def test_choices_are_saved_as_they_are_made(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    qtbot.waitUntil(workspace_path().is_file)
    saved = json.loads(workspace_path().read_text(encoding="utf-8"))
    (batch,) = saved["batches"]["batches"]
    assert batch["key"]["season"] == 1
    assert batch["options"]["stages"]["tracks"]["rules"][0]["verdict"] == "drop"


def test_the_tree_marks_files_with_planned_changes(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    third = controller.tree.index_of(str(library.items[2].file.path))
    assert not third.data(PLANNED)
    roles: list[list[int]] = []
    controller.tree.dataChanged.connect(lambda _a, _b, changed: roles.append(list(changed)))
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    assert controller.tree.index_of(str(library.items[2].file.path)).data(PLANNED)
    assert any(PLANNED in changed for changed in roles)
    # Another batch keeps its own marks while this one is planned again.
    movie = controller.tree.index_of(str(library.items[-3].file.path))
    controller.select(movie)
    settle(controller, qtbot)
    assert controller.tree.index_of(str(library.items[2].file.path)).data(PLANNED)


def test_a_movie_shows_cards_and_saves_to_a_new_profile(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot, episode=len(library.items) - 3)
    assert controller.batch_kind == "movie"
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    audio = controller.movie["groups"][0]
    assert [c["state"] for c in audio["cards"]] == ["kept", "kept", "dropped"]
    assert controller.profile_read_only  # Default cannot be saved over
    controller.save_profile()
    assert controller.profile == "Default"
    assert controller.profile_edited
    assert controller.save_profile_as("").startswith("That cannot be a profile name")
    assert controller.save_profile_as("default") == "A profile named default already exists."
    assert controller.save_profile_as("Movies") == ""
    assert (controller.profile, controller.profile_edited) == ("Movies", False)
    assert controller.movie["groups"][0]["cards"][2]["state"] == "dropped"


def test_the_inspector_follows_the_file_picked_in_a_row(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert controller.inspector["name"] == "Episode Three"
    controller.focus_file(str(library.items[6].file.path))
    assert controller.inspector["name"] == "Episode Seven"
    assert controller.focus_path == str(library.items[6].file.path)
    # Hidden by the filter, the file still shows in the Inspector.
    controller.filter_text = "nothing matches this"
    controller.focus_file(str(library.items[4].file.path))
    assert controller.inspector["name"] == "Episode Five"
    controller.select(QModelIndex())  # an invalid row changes nothing
    assert controller.inspector["name"] == "Episode Five"


def test_the_implied_flags_switch_writes_into_the_working_copy(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert not controller.write_implied_flags
    controller.set_write_implied_flags(True)
    assert controller.write_implied_flags
    assert controller.profile_edited
    assert controller._key is not None
    assert controller.batches.profile(controller._key).for_stage("metadata").write_implied_flags
    settle(controller, qtbot)
    tabs = {tab["key"]: tab["count"] for tab in controller.workspace_tabs}
    # Each fixture file has a track whose name implies a flag it does not have.
    assert (tabs["names"], tabs["review"]) == (10, 10)
    controller.set_write_implied_flags(False)
    assert not controller.profile_edited
