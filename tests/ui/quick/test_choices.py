"""Choices made on Overview and Tracks: live plans in the background, ordinary rules of the place that is open (the
show's working copy, or a season's, an episode's or a movie's own choices), saved to the workspace file as they are
made."""

from __future__ import annotations

import json

from PySide6.QtCore import QModelIndex
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.app.storage.paths import workspace_path
from showrunner.core.media import Episode
from showrunner.stages.tracks import Verdict
from showrunner.ui.quick.library import PLANNED
from showrunner.ui.quick.window import WindowController

ENGLISH, TURKISH, COMMENTARY, STEREO, SDH, ENGLISH_SUBS, FORCED, SRT = range(8)


def open_season(controller: WindowController, library: Library, qtbot: QtBot, episode: int = 2) -> None:
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    controller.model.set_library(library)
    row = controller.tree.index_of(str(library.items[episode].file.path))
    # An episode's row opens that file alone; its season row opens the season. A movie's row opens the movie.
    controller.select(row.parent() if isinstance(library.items[episode].identity, Episode) else row)
    settle(controller, qtbot)


def settle(controller: WindowController, qtbot: QtBot) -> None:
    qtbot.waitUntil(lambda: not controller.planning)


def rules(controller: WindowController) -> list[str]:
    return [" ".join(str(p["text"]) for p in rule["parts"]) for rule in controller.rules]


def column(controller: WindowController, header: dict[str, object]) -> int:
    """The column of the batch open now that stands for the same tracks as `header` of another batch."""
    same = (
        h["id"] for h in controller.matrix["headers"] if (h["code"], h["title"]) == (header["code"], header["title"])
    )
    return int(next(same))


def test_a_show_s_choice_reaches_its_season_and_episode_marked_and_each_can_override_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    controller.toggle_keep(COMMENTARY)
    assert controller.profile_edited  # the show's choices are its profile's working copy
    commentary = controller.matrix["headers"][COMMENTARY]
    assert (commentary["from"], commentary["over"]) == ("", "")
    controller.select(season)
    settle(controller, qtbot)
    header = controller.matrix["headers"][COMMENTARY]
    assert (header["state"], header["from"], header["over"]) == ("dropped", "From the show", "")
    assert controller.overview["groups"][0]["chips"][COMMENTARY]["from"] == "From the show"
    assert [(r["inherited"], r["from"]) for r in controller.rules] == [(True, "From the show")]
    # A rule from the show is changed on the show, not here.
    controller.pause_rule(0, True)
    assert controller.rules[0]["enabled"]
    # Kept in this season only: the season's choice takes the place of the show's on the same tracks.
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    header = controller.matrix["headers"][COMMENTARY]
    assert (header["state"], header["from"], header["over"]) == ("kept", "", "Overrides the show")
    assert [r["inherited"] for r in controller.rules] == [False]
    assert rules(controller) == ["Leave audio in ENG Dolby Digital 2.0 flagged commentary as it is"]
    assert controller.matrix["headers"][COMMENTARY]["short"] == "Own choice"
    assert all(row["cells"][COMMENTARY]["state"] == "kept" for row in controller.matrix["rows"])
    # One episode: its own place, which follows the season and can drop the track for itself alone.
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    settle(controller, qtbot)
    assert controller.batch_kind == "episode"
    assert controller.batch["title"] == "Episode Three"
    at = column(controller, commentary)
    header = controller.matrix["headers"][at]
    assert (header["state"], header["from"]) == ("kept", "From the season")
    controller.toggle_keep(at)
    settle(controller, qtbot)
    assert controller.matrix["headers"][at]["over"] == "Overrides the season"
    controller.select(season)
    settle(controller, qtbot)
    states = [row["cells"][COMMENTARY]["state"] for row in controller.matrix["rows"]]
    assert states[2] == "dropped"
    assert states.count("dropped") == 1


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
    assert rules(controller) == ["Drop audio in ENG Dolby Digital 2.0 flagged commentary"]
    # The season's own choice: the show's profile is not edited by it.
    assert not controller.profile_edited
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["state"] == "dropped"
    assert controller.change_text == "10 changes in 10 files"
    tabs = {tab["key"]: tab["count"] for tab in controller.workspace_tabs}
    assert (tabs["tracks"], tabs["names"], tabs["review"]) == (10, 0, 10)
    # The rule is an ordinary one among the season's own choices.
    assert controller._key is not None
    (rule,) = controller.batches.profile(controller._key).for_stage("tracks").rules
    assert (rule.verdict, rule.from_choice) == (Verdict.DROP, True)
    assert controller.batches.own(controller._key) == {"tracks": {"rules": [rule]}}
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
        "Keep audio in TUR Dolby Digital Plus 5.1 · default",
        "Keep audio in ENG Dolby Digital Plus 5.1 · default if none above",
    ]
    seventh = controller.overview["rows"][6]
    assert seventh["warning"] == "No Turkish audio: English audio becomes the default"
    # Turning the star off again leaves no rule behind: the keep only carried the flag.
    controller.toggle_flag(TURKISH, "default")
    assert rules(controller) == ["Keep audio in ENG Dolby Digital Plus 5.1 · default"]


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
    assert rules(controller) == [
        "Drop subtitles in ENG SubRip flagged hearing impaired",
        "Drop audio in ENG Dolby Digital 2.0 flagged commentary",
    ]
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
    (place,) = saved["batches"]["places"]
    assert (place["key"]["kind"], place["key"]["season"]) == ("season", 1)
    assert place["own"]["tracks"]["rules"][0]["verdict"] == "drop"


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
    movie = controller.tree.index_of(str(library.items[-3].file.path))
    # Dropped on the Movies group, the track is dropped in the movie too, and the profile follows the group.
    controller.select(movie.parent())
    controller.toggle_keep(COMMENTARY)
    assert controller.profile_edited
    controller.select(movie)
    settle(controller, qtbot)
    audio = controller.movie["groups"][0]
    assert [c["state"] for c in audio["cards"]] == ["kept", "kept", "dropped"]
    assert audio["cards"][2]["from"] == "From Movies"
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
    assert controller.inspector["name"] == "Episode One"
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
    assert controller._key is not None
    assert controller.batches.own(controller._key) == {"metadata": {"write_implied_flags": True}}
    assert controller.batches.profile(controller._key).for_stage("metadata").write_implied_flags
    settle(controller, qtbot)
    tabs = {tab["key"]: tab["count"] for tab in controller.workspace_tabs}
    # Each fixture file has a track whose name implies a flag it does not have: the change shows on Tracks and in
    # Review's flag lines, and Names, which shows no template changing, counts none.
    assert (tabs["tracks"], tabs["names"], tabs["review"]) == (10, 0, 10)
    assert not controller.implied_nothing
    controller.set_write_implied_flags(False)
    assert controller.batches.own(controller._key) == {}


def test_a_drop_the_plan_refuses_is_undone_by_a_second_click(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    for column in (ENGLISH, TURKISH, COMMENTARY, STEREO):
        controller.toggle_keep(column)
    settle(controller, qtbot)
    # Every audio track dropped: the plan is refused and the files keep their tracks. The column shows the choice,
    # dropped, and says in how many files the plan keeps the track; the cells show the tracks as the plan leaves them.
    header = controller.matrix["headers"][STEREO]
    assert header["state"] == "dropped"
    assert header["count"].endswith("not dropped in 1 file")
    assert all(row["cells"][STEREO]["state"] != "dropped" for row in controller.matrix["rows"])
    controller.toggle_keep(STEREO)
    settle(controller, qtbot)
    assert rules(controller) == [
        "Drop audio in ENG Dolby Digital Plus 5.1",
        "Drop audio in TUR Dolby Digital Plus 5.1",
        "Drop audio in ENG Dolby Digital 2.0 flagged commentary",
    ]


def codes(controller: WindowController) -> list[str]:
    return [f"{h['code']} {h['title']}" for h in controller.matrix["headers"]]


def test_moving_a_column_sets_the_track_order_of_the_new_files(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    before = codes(controller)
    assert controller.move_track(TURKISH, ENGLISH) == ENGLISH
    # The columns, chips and the Overview show the order at once.
    assert codes(controller) == [before[TURKISH], before[ENGLISH], *before[COMMENTARY:]]
    assert [c["code"] for c in controller.overview["groups"][0]["chips"]][:2] == ["TUR", "ENG"]
    settle(controller, qtbot)
    # Every episode with Turkish audio gets a new file with its own order; Episode Seven has none, so stays as it is.
    assert controller.change_text == "18 changes in 9 files"
    tracks = controller.review["groups"][0]
    assert {line["label"]: line["count"] for line in tracks["lines"]} == {"New file": 9, "Track order": 9}
    assert [t["code"] for t in controller.inspector["tracks"] if t["kind"] == "audio"] == ["TUR", "ENG", "ENG"]
    assert "track order" in controller.review["rows"][0]["summary"]


def test_a_column_moves_only_among_its_kind_and_back_again(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    before = codes(controller)
    # Pushed past the subtitles, an audio column stops at the last audio place.
    assert controller.move_track(ENGLISH, FORCED) == STEREO
    assert codes(controller)[STEREO] == before[ENGLISH]
    assert controller._key is not None
    assert controller.batches.own(controller._key)["tracks"]["order"]
    # Back where the files have it: no order is stored and nothing is planned.
    assert controller.move_track(STEREO, ENGLISH) == ENGLISH
    assert codes(controller) == before
    assert controller.batches.profile(controller._key).for_stage("tracks").order == []
    assert controller.batches.own(controller._key) == {}
    settle(controller, qtbot)
    assert controller.change_count == 0


def test_a_paired_file_moves_ahead_of_the_embedded_subtitles(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(SRT)
    assert controller.move_track(SRT, SDH) == SDH
    assert controller.matrix["headers"][SDH]["paired"]
    settle(controller, qtbot)
    subtitles = [t for t in controller.inspector["tracks"] if t["kind"] == "subtitle"]
    assert subtitles[0]["state"] == "added"


def test_movie_cards_follow_the_track_order(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot, episode=len(library.items) - 3)
    audio = controller.movie["groups"][0]["cards"]
    assert all(c["movable"] for c in audio)
    first, last = audio[0]["id"], audio[-1]["id"]
    assert controller.move_track(last, first) == first
    moved = controller.movie["groups"][0]["cards"]
    assert [c["title"] for c in moved] == [audio[-1]["title"], *(c["title"] for c in audio[:-1])]
    settle(controller, qtbot)
    assert controller.change_count == 2


def test_the_inspector_names_the_new_order(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.move_track(TURKISH, ENGLISH)
    settle(controller, qtbot)
    assert [c["text"] for c in controller.inspector["changes"]][1] == "Tracks in a new order"


def test_the_overview_lead_speaks_of_every_file_only_where_there_are_several(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert "in every file" in controller.overview["lead"]
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    settle(controller, qtbot)
    assert "in this file" in controller.overview["lead"]
