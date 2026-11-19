"""The strip of the Tracks place: what each file's cell under a track draws, quiet where the file follows its track and
a mark of how it differs where it does not; the runs of files that follow every track folded into one; the tooltip."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.media import Episode
from showrunner.ui.quick.window import WindowController

from .conftest import neutral_library
from .test_choices import COMMENTARY, ENGLISH, SRT, STEREO, TURKISH, open_season, settle
from .test_file_rows import _unnamed, path_of

DASH = "\N{EN DASH}"  # between the ends of a folded run


def marks(controller: WindowController, column: int, form: str = "all") -> list[str]:
    return [str(c["mark"]) for c in controller.matrix["strip"][form]["lines"][column]]


def labels(controller: WindowController) -> list[str]:
    return [str(f["label"]) for f in controller.matrix["strip"]["differ"]["files"]]


def tip(controller: WindowController, library: Library, column: int, episode: int) -> str:
    return controller.cell_tip(column, path_of(library, episode))


def test_a_season_as_it_is_is_quiet_where_its_files_follow_and_marks_what_they_lack(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    # Every file has the English default without a choice making it so: the row's D says it, the cells stay quiet.
    assert controller.matrix["headers"][ENGLISH]["default_held"]
    assert marks(controller, ENGLISH) == ["follows"] * 10
    assert marks(controller, TURKISH) == ["follows"] * 6 + ["missing"] + ["follows"] * 3  # Episode Seven lacks it
    assert marks(controller, STEREO) == ["missing"] * 8 + ["follows", "missing"]
    assert marks(controller, SRT) == ["none"] * 10  # a paired file nobody adds draws nothing
    lines = controller.matrix["strip"]["all"]["lines"]
    assert [c["click"] for c in lines[TURKISH]] == [True] * 6 + [False] + [True] * 3
    assert not any(c["click"] for c in lines[SRT])
    assert controller.matrix["strip"]["differing"] == 9
    assert tip(controller, library, TURKISH, 7) == "07 · Episode Seven\nThis file has no TUR Dolby Digital Plus 5.1."
    assert tip(controller, library, ENGLISH, 2) == (
        "02 · Episode Two\nENG Dolby Digital Plus 5.1 kept, as its track has it.\nClick to drop it in this file alone."
    )


def test_a_file_own_drop_and_its_runs_folded_around_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(STEREO)  # under a dropped track a file that lacks it follows: the new file lacks it too
    controller.toggle_file_track(COMMENTARY, path_of(library, 5))
    settle(controller, qtbot)
    assert marks(controller, STEREO) == ["none"] * 10
    assert marks(controller, COMMENTARY) == ["follows"] * 4 + ["own_drop"] + ["follows"] * 5
    assert controller.matrix["strip"]["differing"] == 2  # Episode Five's choice, Episode Seven's missing tracks
    assert labels(controller) == [f"01{DASH}04", "05", "06", "07", f"08{DASH}10"]
    differ = controller.matrix["strip"]["differ"]
    assert differ["files"][0]["paths"] == [path_of(library, n) for n in range(1, 5)]
    assert differ["files"][0]["tip"] == f"01{DASH}04 follow every track"
    assert all(len(line) == 5 for line in differ["lines"])
    assert [c["mark"] for c in differ["lines"][COMMENTARY]] == ["follows", "own_drop", "follows", "follows", "follows"]
    assert [c["click"] for c in differ["lines"][COMMENTARY]] == [False, True, True, True, False]  # a run is no file
    assert tip(controller, library, COMMENTARY, 5) == (
        "05 · Episode Five\nENG Dolby Digital 2.0 dropped here by this file's own choice.\n"
        "Click to follow its track again."
    )


def test_a_file_own_keep_under_a_dropped_track(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    controller.toggle_file_track(COMMENTARY, path_of(library, 3))
    settle(controller, qtbot)
    assert marks(controller, COMMENTARY) == ["none"] * 2 + ["own_keep"] + ["none"] * 7
    assert tip(controller, library, COMMENTARY, 1).endswith(
        "dropped, as its track has it.\nClick to keep it in this file alone."
    )


def test_a_default_that_falls_to_another_track_is_the_fallback(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_flag(TURKISH, "default")
    controller.toggle_flag(ENGLISH, "default")
    settle(controller, qtbot)
    # Turkish is tried first; Episode Seven has none, so its default falls to English.
    assert marks(controller, ENGLISH) == ["follows"] * 6 + ["fallback"] + ["follows"] * 3
    assert "the first choice has no track in this file" in tip(controller, library, ENGLISH, 7)


def test_each_file_own_default_shows_where_the_files_differ(qtbot: QtBot, controller: WindowController) -> None:
    library = neutral_library()

    def plain(item: Any) -> Any:  # Episode Two's English audio is not the default
        if not isinstance(item.identity, Episode) or (item.identity.season, item.identity.episode) != (1, 2):
            return item
        tracks = tuple(replace(t, flags=replace(t.flags, default=False)) if t.id == 1 else t for t in item.file.tracks)
        return replace(item, file=replace(item.file, tracks=tracks))

    library = replace(library, items=tuple(plain(i) for i in library.items))
    open_season(controller, library, qtbot)
    header = controller.matrix["headers"][ENGLISH]
    assert (header["default"], header["default_held"]) == (False, False)  # the row's D is the faint letter
    assert marks(controller, ENGLISH) == ["file_default", "follows"] + ["file_default"] * 8


def test_a_choice_on_a_name_drops_or_keeps_beside_its_track(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    library = _unnamed(library, 3)  # the commentary of Episodes One to Three has no name, the others name theirs
    open_season(controller, library, qtbot)
    controller.toggle_name(COMMENTARY, "Commentary")
    settle(controller, qtbot)
    assert marks(controller, COMMENTARY) == ["follows"] * 3 + ["drop"] * 7
    assert "dropped here by the choice on its name" in tip(controller, library, COMMENTARY, 4)
    # Dropped as a track, the named ones kept by their name: not a plan that was refused.
    controller.toggle_name(COMMENTARY, "Commentary")
    controller.toggle_keep(COMMENTARY)
    controller.toggle_name(COMMENTARY, "Commentary")
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["state"] == "dropped"
    assert marks(controller, COMMENTARY) == ["none"] * 3 + ["keep"] * 7
    assert "kept here by the choice on its name" in tip(controller, library, COMMENTARY, 4)


def test_a_track_kept_by_a_refused_plan_is_held(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(ENGLISH)
    controller.toggle_keep(COMMENTARY)  # Episode Seven, without Turkish audio, would keep no audio at all
    settle(controller, qtbot)
    assert marks(controller, ENGLISH)[6] == marks(controller, COMMENTARY)[6] == "held"
    assert marks(controller, ENGLISH)[:6] == ["none"] * 6
    assert "not dropped here." in tip(controller, library, ENGLISH, 7)


def test_a_choice_of_a_place_nearer_the_file_is_not_its_own(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(path_of(library, 1)).parent()
    controller.toggle_keep(COMMENTARY)  # the first season drops the commentary
    settle(controller, qtbot)
    controller.select(season.parent())  # the show, whose second season keeps it
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["state"] == "kept"
    assert marks(controller, COMMENTARY) == ["drop"] * 10 + ["follows"] * 8
    assert "dropped here by a choice made nearer the file" in tip(controller, library, COMMENTARY, 1)
    seasons = controller.matrix["strip"]["all"]["seasons"]
    assert [(s["label"], s["first"], s["count"]) for s in seasons] == [("Season 1", 0, 10), ("Season 2", 10, 8)]
    assert controller.matrix["strip"]["all"]["files"][10]["label"] == "01"
    assert labels(controller)[0] == "S01E01"
