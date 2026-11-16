"""The window controller and the library tree it hands to QML."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QUrl
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library, LibraryLoad
from showrunner.app.library.loader import LibraryLoader
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.settings.app_settings import load_settings
from showrunner.app.storage.paths import workspace_path
from showrunner.tools.probe import Programs
from showrunner.ui.quick.library import KIND, LABEL, NUMBER, PROBLEM, ROW_ID, SUMMARY
from showrunner.ui.quick.window import WindowController, local_paths


def select_path(controller: WindowController, path: Path) -> None:
    controller.select(controller.tree.index_of(str(path)))


def test_programs_are_checked_in_the_background(controller: WindowController, qtbot: QtBot) -> None:
    assert [row["state"] for row in controller.programs] == ["checking", "checking"]
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    mkvtoolnix, ffmpeg = controller.programs
    assert (mkvtoolnix["found"], mkvtoolnix["status"]) == (True, "MKVToolNix 88.0")
    assert (ffmpeg["found"], ffmpeg["status"]) == (False, "FFmpeg not found")


def test_get_it_opens_programs_and_a_change_there_checks_again(
    controller: WindowController, opened: list[str], qtbot: QtBot
) -> None:
    controller.get_program("ffmpeg")
    assert opened == ["ffmpeg"]
    with qtbot.waitSignal(controller.programs_changed):
        controller.settings.programs.statuses_changed.emit()


def test_the_tree_draws_from_named_roles(controller: WindowController, library: Library) -> None:
    controller.model.set_library(library)
    tree = controller.tree
    seventh = tree.index_of(str(library.items[6].file.path))
    assert seventh.data(KIND) == "episode"
    assert (seventh.data(NUMBER), seventh.data(LABEL), seventh.data(SUMMARY)) == ("07", "Episode Seven", "tur")
    assert seventh.data(PROBLEM) == "change"
    show = tree.index_of(seventh.parent().parent().data(ROW_ID))
    assert (show.data(LABEL), show.data(SUMMARY), show.data(PROBLEM)) == ("Show Name (2020)", "18", "")
    assert tree.columnCount() == 1
    assert controller.needs_look == 1


def test_the_filter_and_needs_a_look_narrow_the_tree(controller: WindowController, library: Library) -> None:
    controller.model.set_library(library)
    controller.filter_text = "Third"
    assert controller.tree.index_of(str(library.items[-1].file.path)).isValid()
    assert not controller.tree.index_of(str(library.items[0].file.path)).isValid()
    controller.filter_text = ""
    controller.needs_look_only = True
    assert controller.tree.index_of(str(library.items[6].file.path)).isValid()
    assert not controller.tree.index_of(str(library.items[5].file.path)).isValid()


def test_an_episode_opens_its_season(controller: WindowController, library: Library) -> None:
    controller.model.set_library(library)
    select_path(controller, library.items[2].file.path)
    assert controller.has_batch
    assert controller.batch_kind == "season"
    assert controller.batch["title"] == "Season 1"
    assert controller.selected == str(library.items[2].file.path)
    assert controller.selected_index.isValid()
    assert controller.side_tabs("overview") == [
        {"key": "inspector", "count": -1},
        {"key": "chapters", "count": 8},
        {"key": "attachments", "count": 2},
    ]
    assert controller.side_tabs("review") == []
    assert [tab["key"] for tab in controller.workspace_tabs][:4] == ["overview", "tracks", "names", "review"]


def test_groups_open_their_batch(controller: WindowController, library: Library) -> None:
    controller.model.set_library(library)
    episode = controller.tree.index_of(str(library.items[0].file.path))
    controller.select(episode.parent())
    assert (controller.batch_kind, controller.batch["title"]) == ("season", "Season 1")
    controller.select(episode.parent().parent())
    assert (controller.batch_kind, controller.batch["title"]) == ("show", "Show Name (2020)")
    movie = controller.tree.index_of(str(library.items[-1].file.path))
    controller.select(movie)
    assert controller.batch_kind == "movie"
    controller.select(movie.parent())
    assert (controller.batch_kind, controller.batch["title"]) == ("selection", "Movies")


def test_the_pill_switches_the_selected_batch(controller: WindowController, library: Library) -> None:
    ProfileStore().duplicate("Default", "Series")
    controller.model.set_library(library)
    assert controller.profile == "Default"
    select_path(controller, library.items[0].file.path)
    assert "Series" in controller.profiles
    controller.switch_profile("Series")
    assert controller.profile == "Series"
    select_path(controller, library.items[-1].file.path)
    assert controller.profile == "Default"


def test_an_edited_batch_is_discarded_before_it_switches(controller: WindowController, library: Library) -> None:
    ProfileStore().duplicate("Default", "Series")
    controller.model.set_library(library)
    select_path(controller, library.items[0].file.path)
    assert controller._key is not None
    copy = controller.batches.copy(controller._key)
    copy.set_options("tracks", type(copy.profile.options["tracks"])(flags_from_names=False))
    assert controller.profile_edited
    controller.switch_profile("Series")
    assert controller.profile == "Default"
    controller.discard_profile()
    assert not controller.profile_edited
    controller.switch_profile("Series")
    assert controller.profile == "Series"


def test_panel_sizes_are_kept_in_the_settings(controller: WindowController) -> None:
    assert controller.panel_state("columns").isEmpty()
    controller.save_panel_state("columns", QByteArray(b"\x00\x01state"))
    assert bytes(controller.panel_state("columns").data()) == b"\x00\x01state"
    assert "columns" in load_settings().value.panel_sizes


def test_the_height_of_the_tracks_box_is_kept_in_the_settings(controller: WindowController) -> None:
    assert controller.overview_tracks_height() == 0
    controller.save_overview_tracks_height(280)
    assert controller.overview_tracks_height() == 280
    assert load_settings().value.overview_tracks_height == 280
    assert load_settings().value.panel_sizes == {}  # a setting of its own, not a panel's saved state


def test_only_local_urls_are_read(tmp_path: Path) -> None:
    file = tmp_path / "x.mkv"
    urls = [
        QUrl.fromLocalFile(str(tmp_path)),
        QUrl("https://example.com/a.mkv"),
        QUrl.fromLocalFile(str(file)).toString(),
    ]
    assert local_paths(urls) == [tmp_path, file]


def test_a_dropped_folder_loads_and_is_remembered(qtbot: QtBot, tmp_path: Path, opened: list[str]) -> None:
    folder = tmp_path / "media" / "Show Name (2020)"
    video = folder / "Season 1" / "Show Name - S01E01.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    loader = LibraryLoader(programs=Programs(None, None, None))
    controller = WindowController(loader=loader, get_program=opened.append)
    with qtbot.waitSignal(controller.library_changed):
        controller.add_urls([QUrl.fromLocalFile(str(folder))])
    controller.add_urls([QUrl.fromLocalFile(str(folder))])  # a second drop while reading is ignored
    qtbot.waitUntil(lambda: not controller.busy)
    assert controller.loaded
    assert controller.has_batch
    assert [entry["name"] for entry in controller.recent] == ["Show Name (2020)"]

    controller.save_workspace()
    settings = load_settings().value
    assert settings.last_folders == [str(folder)]
    assert list(settings.recent_folders) == [str(folder)]
    assert json.loads(workspace_path().read_text(encoding="utf-8"))["format"] == 1

    again = WindowController(loader=LibraryLoader(programs=Programs(None, None, None)), get_program=opened.append)
    with qtbot.waitSignal(again.library_changed):
        again.restore_workspace()
    qtbot.waitUntil(lambda: not again.busy)
    assert again.model.library.items[0].file.path == video


def test_a_second_load_refreshes_the_selected_batch(controller: WindowController, library: Library) -> None:
    season = library.items[:10]
    controller._on_loaded(LibraryLoad(items=season[:2]))
    select_path(controller, season[0].file.path)
    assert controller.batch["facts"].startswith("2 episodes")
    controller._on_loaded(LibraryLoad(items=season[2:]))
    assert controller.selected == str(season[0].file.path)
    assert controller.batch["facts"].startswith("10 episodes")


def test_the_status_bar_says_how_a_load_ended(controller: WindowController) -> None:
    assert controller.job_text == "No jobs running"
    controller._on_loaded(LibraryLoad())
    assert controller.job_text == "No new videos found."
    controller._on_failed(OSError("denied"))
    assert controller.job_text == "The folder could not be read: denied"
