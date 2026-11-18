"""Every tab and action follows the nearest place: the fields mark where their values come from, a season's text
follows an episode's own choices, Keep these files as they are, and Apply on any place, one episode included."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.batches.batch import BatchKey
from showrunner.ui.quick.library import KEPT
from showrunner.ui.quick.tracks import item_title
from showrunner.ui.quick.window import WindowController

from .test_apply import Setup, make_setup


@pytest.fixture
def setup(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> Iterator[Setup]:
    made = make_setup(qtbot, tmp_path)
    yield made
    made.hold.set()
    made.controller.stop_jobs()
    made.controller.deleteLater()


def _open(setup: Setup, qtbot: QtBot, path: Path | None = None, *, up: int = 1) -> None:
    """Open the row of `path` (the season's first file by default), or the row `up` levels above it."""
    index = setup.controller.tree.index_of(str(path or setup.season[0]))
    for _ in range(up):
        index = index.parent()
    setup.controller.select(index)
    qtbot.waitUntil(lambda: not setup.controller.planning)


def _title_mark(controller: WindowController) -> dict[str, str]:
    return controller.field_marks["naming.title_template"]


def test_a_field_is_marked_with_the_place_it_comes_from_and_can_be_overridden(setup: Setup, qtbot: QtBot) -> None:
    controller, third = setup.controller, setup.season[2]
    _open(setup, qtbot, up=2)
    assert controller.field_marks == {}  # a show has nothing above it
    controller.start_template("title_template")
    _open(setup, qtbot)
    assert _title_mark(controller) == {"from": "From the show", "over": ""}
    assert controller.field_marks["metadata.untagged_language"] == {"from": "", "over": ""}
    # "As it is" is a value too: the season clears the template over the show's.
    controller.clear_template()
    assert _title_mark(controller) == {"from": "", "over": "Overrides the show"}
    _open(setup, qtbot, third, up=0)
    assert _title_mark(controller)["from"] == "From the season"
    # Discard on the season removes its own value only; the show keeps the template.
    _open(setup, qtbot)
    # Its commentary choice from the setup and the cleared template.
    assert controller.discard_question["text"].startswith("Season 1 loses 2 choices of its own")
    controller.discard_changes()
    assert _title_mark(controller)["from"] == "From the show"


def test_the_season_s_text_follows_an_episode_s_own_choices(setup: Setup, qtbot: QtBot) -> None:
    controller, third = setup.controller, setup.season[2]
    _open(setup, qtbot)
    controller.start_template("title_template")
    _open(setup, qtbot, third, up=0)
    controller.clear_template()
    controller.set_original("keep")
    _open(setup, qtbot)
    controller.show_place("names")
    rows = {row["path"]: row for row in controller.names["rows"]}
    # The pipeline here has no metadata stage, so a row shows the name each file's own template makes.
    assert rows[str(third)]["after"] == rows[str(third)]["now"]  # as it is in that episode
    assert rows[str(setup.season[0])]["after"] != rows[str(setup.season[0])]["now"]
    controller.focus_file(str(third))
    assert controller.names["result"]["stays"]
    assert (
        next(c for c in controller.names["cards"] if c["key"] == "title_template")["sample"]
        == "Titles stay as they are"
    )
    assert "keep folder" in json.dumps(controller.inspector)
    controller.focus_file(str(setup.season[0]))
    assert "Recycle Bin" in json.dumps(controller.inspector)


def test_review_names_the_episode_whose_own_choice_blocks_a_stage(setup: Setup, qtbot: QtBot) -> None:
    controller, third = setup.controller, setup.season[2]
    key = BatchKey.file(next(i for i in setup.library.items if i.file.path == third))
    naming = controller.batches.profile(key).for_stage("naming")
    controller.batches.set_options(key, "naming", replace(naming, title_template="{nope}"))
    controller.profiles_edited()
    qtbot.waitUntil(lambda: not controller.planning)
    episode = item_title(next(i for i in setup.library.items if i.file.path == third))
    problems = [line for group in controller.review["groups"] for line in group["problems"]]
    assert any(line.startswith(f"{episode}: ") for line in problems)


def test_keep_these_files_as_they_are_cancels_what_comes_from_above_and_discard_takes_it_back(
    setup: Setup, qtbot: QtBot
) -> None:
    controller, fourth = setup.controller, setup.season[3]
    _open(setup, qtbot, up=2)
    assert [a["key"] for a in controller.place_actions] == ["discard", "exclude", "queue"]  # nothing above a show
    _open(setup, qtbot, fourth, up=0)
    every = controller.change_count
    assert every > 0
    keep = next(a for a in controller.place_actions if a["key"] == "keep")
    assert keep == {"key": "keep", "text": "Keep these files as they are", "enabled": True}
    controller.place_action("keep")
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count == 0
    assert controller.kept_text.startswith("Kept as they are: nothing from the season reaches these files.")
    assert not next(a for a in controller.place_actions if a["key"] == "keep")["enabled"]
    assert controller.can_discard
    # The season and its other episodes keep the season's choices; the kept one plans nothing.
    _open(setup, qtbot)
    assert controller.kept_text == ""
    assert next(r for r in controller.review["rows"] if r["path"] == str(fourth))["count"] == 0
    # Discard on the episode takes the keep back without asking.
    _open(setup, qtbot, fourth, up=0)
    asked: list[bool] = []
    controller.discard_asked.connect(lambda: asked.append(True))
    controller.ask_discard()
    qtbot.waitUntil(lambda: not controller.planning)
    assert asked == []
    assert controller.change_count == every
    assert controller.kept_text == ""


def test_apply_on_one_episode_writes_that_file_alone(setup: Setup, qtbot: QtBot) -> None:
    controller, fourth = setup.controller, setup.season[3]
    _open(setup, qtbot, fourth, up=0)
    assert controller.batch_kind == "episode"
    assert controller.can_apply
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    assert [r["state"] for r in controller.jobs.view["rows"]] == ["done"]
    assert [p.name for p in setup.bin.iterdir()] == [fourth.name]
    assert all(path.read_bytes() == b"original" for path in setup.season if path != fourth)


def test_apply_on_the_season_leaves_a_kept_episode_as_it_is(setup: Setup, qtbot: QtBot) -> None:
    controller, fourth = setup.controller, setup.season[3]
    _open(setup, qtbot, fourth, up=0)
    controller.keep_place()
    _open(setup, qtbot)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    assert fourth.read_bytes() == b"original"
    assert sorted(p.name for p in setup.bin.iterdir()) == sorted(p.name for p in setup.season if p != fourth)


def test_leaving_a_place_drops_what_its_places_set_to_what_they_receive(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    _open(setup, qtbot)
    controller.start_template("title_template")
    assert _title_mark(controller)["over"] == ""
    _open(setup, qtbot, up=2)
    controller.start_template("title_template")  # the show now gives what the season set
    _open(setup, qtbot)
    assert _title_mark(controller)["from"] == "From the show"
    assert "1 choice of its own" in controller.discard_question["text"]  # the commentary choice alone is left


def _header(controller: WindowController, **found: object) -> dict:
    return next(h for h in controller.matrix["headers"] if all(h.get(k) == v for k, v in found.items()))


def _write(paths: list[Path]) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"original")


def test_a_group_left_out_on_a_season_stays_out_in_its_episodes_unless_one_puts_it_back(
    setup: Setup, qtbot: QtBot
) -> None:
    controller, fourth = setup.controller, setup.season[3]
    _open(setup, qtbot)
    controller.set_in_run("tracks", False)
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count == 0
    _open(setup, qtbot, fourth, up=0)
    assert not next(g for g in controller.review["groups"] if g["key"] == "tracks")["in_run"]
    controller.set_in_run("tracks", True)  # the episode's own value
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count > 0
    _open(setup, qtbot)
    counts = {r["path"]: r["count"] for r in controller.review["rows"]}
    assert counts[str(fourth)] > 0
    assert all(count == 0 for path, count in counts.items() if path != str(fourth))
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    assert [p.name for p in setup.bin.iterdir()] == [fourth.name]
    qtbot.waitUntil(lambda: not controller.locked)  # the written file is read again first
    # Putting it back on the season makes the episode's equal value go.
    controller.set_in_run("tracks", True)
    assert controller.left_out.empty


def test_not_this_time_is_kept_by_the_file_s_place_in_every_view(setup: Setup, qtbot: QtBot) -> None:
    controller, fourth = setup.controller, setup.season[3]
    _open(setup, qtbot)
    controller.set_file_in_run(str(fourth), False)
    _open(setup, qtbot, fourth, up=0)
    assert controller.review["rows"][0]["state"] == "out"
    _open(setup, qtbot, up=2)
    assert next(r for r in controller.review["rows"] if r["path"] == str(fourth))["state"] == "out"
    assert next(r for r in controller.review["rows"] if r["path"] == str(setup.season[0]))["state"] != "out"


def test_the_season_lists_names_when_only_an_episode_sets_a_template(setup: Setup, qtbot: QtBot) -> None:
    controller, third = setup.controller, setup.season[2]
    _open(setup, qtbot, third, up=0)
    controller.start_template("title_template")
    _open(setup, qtbot)
    controller.show_place("names")
    assert controller.names["empty"]
    assert controller.names["listed"]
    card = next(c for c in controller.names["cards"] if c["key"] == "title_template")
    assert not card["empty"]
    rows = {row["path"]: row for row in controller.names["rows"]}
    assert rows[str(third)]["after"] != rows[str(third)]["now"]
    assert rows[str(setup.season[0])]["after"] == rows[str(setup.season[0])]["now"]


def test_paired_files_and_flags_from_names_are_marked_where_they_come_from(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    _open(setup, qtbot, up=2)
    paired = _header(controller, paired=True)
    controller.toggle_keep(paired["id"])  # the show adds the paired files
    controller.set_flags_from_names(False)
    _open(setup, qtbot)
    assert _header(controller, paired=True)["from"] == "From the show"
    assert controller.field_marks["tracks.flags_from_names"]["from"] == "From the show"
    # The season leaves the paired file out and reads flags from names again: both override the show.
    paired = _header(controller, paired=True)
    controller.toggle_keep(paired["id"])
    controller.set_flags_from_names(True)
    qtbot.waitUntil(lambda: not controller.planning)
    assert _header(controller, paired=True)["over"] == "Overrides the show"
    assert controller.field_marks["tracks.flags_from_names"]["over"] == "Overrides the show"
    assert "short" not in controller.field_marks["tracks.flags_from_names"]
    assert "mux.keep_folder" not in controller.field_marks


def test_a_kept_place_is_marked_on_its_library_row(setup: Setup, qtbot: QtBot) -> None:
    controller, fourth = setup.controller, setup.season[3]
    row = controller.tree.index_of(str(fourth))
    _open(setup, qtbot, fourth, up=0)
    assert controller.tree.data(row, KEPT) is False
    controller.keep_place()
    assert controller.tree.data(row, KEPT) is True
    assert controller.tree.data(row.parent(), KEPT) is False  # the season itself is not kept
    controller.ask_discard()
    assert controller.tree.data(row, KEPT) is False


def test_apply_on_a_whole_show_writes_every_season(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    second = [i.file.path for i in setup.library.items if i.file.path.parent.name == "Season 2"]
    second = [p for p in second if p.parent.parent.name == "Show Name (2020)"]
    _write(second)
    _open(setup, qtbot, up=2)
    controller.toggle_keep(2)  # the show drops the commentary; Season 1 drops it on its own already
    qtbot.waitUntil(lambda: not controller.planning and controller.can_apply)
    with qtbot.waitSignal(controller.jobs.ended, timeout=20_000):
        controller.apply()
    assert sorted(p.name for p in setup.bin.iterdir()) == sorted(p.name for p in [*setup.season, *second])


def _movies(setup: Setup) -> list[Path]:
    movies = [i.file.path for i in setup.library.items if "Movie" in i.file.path.name]
    _write(movies)
    return movies


def _drop_commentary(controller: WindowController, qtbot: QtBot) -> None:
    column = next(h["id"] for h in controller.matrix["headers"] if h["name"] == "Commentary")
    controller.toggle_keep(column)
    qtbot.waitUntil(lambda: not controller.planning and controller.can_apply)


def test_apply_on_one_movie_writes_that_movie_alone(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    movies = _movies(setup)
    _open(setup, qtbot, movies[1], up=0)
    assert controller.batch_kind == "movie"
    _drop_commentary(controller, qtbot)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    assert [p.name for p in setup.bin.iterdir()] == [movies[1].name]


def test_apply_on_the_movies_group_writes_its_movies(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    movies = _movies(setup)
    _open(setup, qtbot, movies[0])
    assert controller.batch_kind == "movies"
    _drop_commentary(controller, qtbot)
    planned = [r["path"] for r in controller.review["rows"] if r["count"] > 0]
    assert planned
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    assert sorted(p.name for p in setup.bin.iterdir()) == sorted(Path(p).name for p in planned)
