"""Remove from list, Close folder in the library's menu, and Home over an open library: what is taken out of the list
stays out across a restart and a reload of its folder until the folder is added again, Close folder closes only the
folders the row comes from, and Home shows the start screen without closing anything."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.batches.batch import Batches, BatchKey
from showrunner.app.library.loader import LibraryLoader
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.settings.app_settings import load_settings
from showrunner.app.storage.paths import workspace_path
from showrunner.tools.probe import Programs
from showrunner.ui.quick.window import WindowController

from .conftest import program_statuses
from .test_choices import settle
from .test_discard import _all, _click, _evaluate, _named, _row, _visible


def _controller() -> WindowController:
    return WindowController(
        statuses=program_statuses, loader=LibraryLoader(programs=Programs(None, None, None)), get_program=lambda _: None
    )


@pytest.fixture
def controller(qapp: QApplication) -> Iterator[WindowController]:
    controller = _controller()
    yield controller
    controller.deleteLater()


@pytest.fixture
def folders(make: Callable[..., Path], tmp_path: Path) -> tuple[Path, Path]:
    """Show Name (2020) with two seasons and Another Show (2018) with one, in two folders."""
    for relative in (
        "media/Show Name (2020)/Season 1/Show Name - S01E01.mkv",
        "media/Show Name (2020)/Season 1/Show Name - S01E02.mkv",
        "media/Show Name (2020)/Season 2/Show Name - S02E01.mkv",
        "media/Another Show (2018)/Season 1/Another Show - S01E01.mkv",
    ):
        make(relative)
    media = tmp_path / "media"
    return media / "Show Name (2020)", media / "Another Show (2018)"


def open_folders(controller: WindowController, qtbot: QtBot, *paths: Path) -> None:
    controller.add_paths(list(paths))
    qtbot.waitUntil(lambda: not controller.busy)


def listed(controller: WindowController) -> list[str]:
    return [i.file.path.name for i in controller.model.library.items]


def row(controller: WindowController, folder: Path, name: str, up: int = 0) -> QModelIndex:
    """The row of a video of `folder`, or the row `up` levels above it (1 its season, 2 its show)."""
    index = controller.tree.index_of(str(next(folder.rglob(name))))
    for _ in range(up):
        index = index.parent()
    return index


def pick(controller: WindowController, qtbot: QtBot, index: QModelIndex) -> None:
    controller.select(index)
    settle(controller, qtbot)


def keys(controller: WindowController) -> list[str]:
    return [a["key"] for a in controller.place_actions]


def saved_removed() -> list[str]:
    return json.loads(workspace_path().read_text(encoding="utf-8"))["batches"]["removed"]


def test_a_season_and_then_an_episode_are_taken_out_of_the_list_and_stay_on_disk(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv", up=1))
    assert controller.batch["title"] == "Season 1"
    controller.place_action("remove")
    assert listed(controller) == ["Another Show - S01E01.mkv", "Show Name - S02E01.mkv"]
    assert controller.batches.removed == {show / "Season 1" / f"Show Name - S01E0{n}.mkv" for n in (1, 2)}
    assert (show / "Season 1" / "Show Name - S01E01.mkv").is_file()
    assert controller.has_batch  # the first row that is left opens
    pick(controller, qtbot, row(controller, show, "Show Name - S02E01.mkv"))
    controller.place_action("remove")
    assert listed(controller) == ["Another Show - S01E01.mkv"]
    assert controller.loaded
    controller._save_batches()
    assert len(saved_removed()) == 3


def test_a_whole_show_is_taken_out_with_what_lies_inside_it(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv", up=2))
    controller.place_action("remove")
    assert listed(controller) == ["Another Show - S01E01.mkv"]
    assert len(controller.batches.removed) == 3
    assert controller.model.library.roots == (show, other)  # the folders stay open


def test_what_was_removed_stays_out_after_a_restart_and_comes_back_when_its_folder_is_added_again(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E02.mkv"))
    controller.exclude_place(True)  # the place's exclusion is kept while it is away
    controller.place_action("remove")
    controller.save_workspace()
    assert listed(controller) == ["Another Show - S01E01.mkv", "Show Name - S01E01.mkv", "Show Name - S02E01.mkv"]

    again = _controller()
    again.restore_workspace()
    qtbot.waitUntil(lambda: not again.busy and again.loaded)
    assert listed(again) == listed(controller)  # the reload of both folders left it out
    assert again.batches.removed == controller.batches.removed

    removed = show / "Season 1" / "Show Name - S01E02.mkv"
    open_folders(again, qtbot, other)  # another folder: it stays out
    assert removed.name not in listed(again)
    open_folders(again, qtbot, show)  # the folder again, through the drop zone or "+"
    assert removed.name in listed(again)
    assert again.batches.removed == set()
    pick(again, qtbot, again.tree.index_of(str(removed)))
    assert again.place_excluded  # its choices came back with it
    again.deleteLater()


def test_a_removed_file_comes_back_when_a_folder_above_it_is_added(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, show)
    pick(controller, qtbot, row(controller, show, "Show Name - S02E01.mkv"))
    controller.place_action("remove")
    assert "Show Name - S02E01.mkv" not in listed(controller)
    open_folders(controller, qtbot, show.parent)
    assert "Show Name - S02E01.mkv" in listed(controller)


def test_a_file_dropped_on_its_own_is_listed_again_by_adding_that_file(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, show)
    video = show / "Season 2" / "Show Name - S02E01.mkv"
    pick(controller, qtbot, controller.tree.index_of(str(video)))
    controller.place_action("remove")
    open_folders(controller, qtbot, show / "Season 1" / "Show Name - S01E01.mkv")
    assert video.name not in listed(controller)  # a different file
    open_folders(controller, qtbot, video)
    assert video.name in listed(controller)


def test_the_removed_set_is_forgotten_when_the_library_is_closed(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, show)
    pick(controller, qtbot, row(controller, show, "Show Name - S02E01.mkv"))
    controller.place_action("remove")
    assert controller.batches.removed
    controller.close_folder()
    assert controller.batches.removed == set()


def test_removing_the_last_videos_shows_home_and_keeps_the_folders_for_the_next_start(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    _, other = folders
    open_folders(controller, qtbot, other)
    pick(controller, qtbot, row(controller, other, "Another Show - S01E01.mkv", up=2))
    controller.save_workspace()
    controller.place_action("remove")
    assert not controller.loaded
    assert controller.home_shown
    assert load_settings().value.last_folders == [str(other)]


def test_old_workspace_files_without_a_removed_list_load(tmp_path: Path) -> None:
    store = ProfileStore()
    assert Batches.from_json(store, {"excluded": []}).removed == set()
    junk = Batches.from_json(store, {"removed": ["a/b.mkv", 3, "", None]}).removed
    assert junk == {Path("a/b.mkv")}
    assert Batches.from_json(store, {"removed": "a/b.mkv"}).removed == set()
    batches = Batches(store)
    batches.removed.add(tmp_path / "one.mkv")
    assert Batches.from_json(store, batches.to_json()).removed == {tmp_path / "one.mkv"}


def test_a_removed_place_keeps_no_row_and_cannot_be_removed_while_a_folder_is_being_read(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, show)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv", up=1))
    assert next(a for a in controller.place_actions if a["key"] == "remove")["enabled"]
    controller.add_paths([other])
    assert controller._loader.busy
    assert not next(a for a in controller.place_actions if a["key"] == "remove")["enabled"]
    controller.remove_place()
    assert controller.batches.removed == set()
    qtbot.waitUntil(lambda: not controller.busy)


# Close folder


def test_close_folder_in_the_menu_closes_only_the_folder_of_the_show(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, other, "Another Show - S01E01.mkv", up=2))
    assert keys(controller)[-2:] == ["remove", "close"]
    close = next(a for a in controller.place_actions if a["key"] == "close")
    assert close["text"] == "Close folder"
    assert "Another Show (2018)" in close["tip"]
    assert "Show Name (2020)" not in close["tip"]
    controller.place_action("close")
    assert controller.model.library.roots == (show,)
    assert listed(controller) == ["Show Name - S01E01.mkv", "Show Name - S01E02.mkv", "Show Name - S02E01.mkv"]
    assert controller.loaded
    assert controller.has_batch
    assert load_settings().value.last_folders == [str(show)]
    assert all(show.joinpath("Season 1", f"Show Name - S01E0{n}.mkv").is_file() for n in (1, 2))


def test_closing_the_only_folder_is_back_to_home(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, show)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv", up=2))
    controller.place_action("close")
    assert not controller.loaded
    assert controller.home_shown
    assert load_settings().value.last_folders == []


def test_close_folder_is_offered_on_a_show_only_and_not_for_files_opened_one_by_one(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, show)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv", up=1))
    assert "close" not in keys(controller)  # a season: the folder is not the place's to close
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv"))
    assert "close" not in keys(controller)
    open_folders(controller, qtbot, other / "Season 1" / "Another Show - S01E01.mkv")
    pick(controller, qtbot, row(controller, other, "Another Show - S01E01.mkv", up=2))
    assert "close" not in keys(controller)  # opened as a file, so there is no folder


def test_a_folder_with_several_shows_closes_them_all(
    controller: WindowController, make: Callable[..., Path], tmp_path: Path, qtbot: QtBot
) -> None:
    make("lib/Show Name (2020)/Season 1/Show Name - S01E01.mkv")
    make("lib/Another Show (2018)/Season 1/Another Show - S01E01.mkv")
    make("kept/Third Show (2016)/Season 1/Third Show - S01E01.mkv")
    open_folders(controller, qtbot, tmp_path / "lib", tmp_path / "kept")
    pick(controller, qtbot, row(controller, tmp_path / "lib", "Another Show - S01E01.mkv", up=2))
    close = next(a for a in controller.place_actions if a["key"] == "close")
    assert close["tip"].startswith("Closes lib ")
    controller.place_action("close")
    assert listed(controller) == ["Third Show - S01E01.mkv"]


# Home


def test_home_shows_the_start_screen_and_keeps_everything_open(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E02.mkv"))
    controller.exclude_place(True)
    selected, items, roots = controller.selected, listed(controller), controller.model.library.roots
    assert not controller.home_shown
    controller.go_home()
    assert controller.home_shown
    assert controller.loaded  # nothing was closed
    assert (controller.selected, listed(controller), controller.model.library.roots) == (selected, items, roots)
    assert controller.place_excluded
    assert controller.has_batch
    controller.leave_home()
    assert not controller.home_shown
    assert controller.selected == selected


def test_a_click_on_a_library_row_or_a_new_folder_leaves_home_but_a_background_read_does_not(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, show)
    controller.go_home()
    controller._reselect()  # as after a job's files were read again
    assert controller.home_shown
    pick(controller, qtbot, row(controller, show, "Show Name - S02E01.mkv"))
    assert not controller.home_shown
    controller.go_home()
    open_folders(controller, qtbot, other)
    assert not controller.home_shown  # what was just opened is shown


def test_home_changes_nothing_that_is_saved(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, show)
    controller.go_home()
    controller.save_workspace()
    assert load_settings().value.last_folders == [str(show)]
    assert BatchKey.movies() not in controller.batches.exclusions.values


def test_home_does_nothing_without_a_library(controller: WindowController) -> None:
    controller.go_home()
    assert controller.home_shown  # Home already, and no flag is left to hold it after a folder is opened
    assert not controller._at_home


def test_the_palette_offers_home_while_a_library_is_open(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, show)
    controller.palette_query = "home"
    assert [(r["key"], r["label"]) for r in controller.palette if r["kind"] == "action"] == [("home", "Go to Home")]
    controller.palette_run("action", "home")
    assert controller.home_shown
    controller.palette_query = "home"
    assert [r for r in controller.palette if r["kind"] == "action"] == []


# In the window


def test_the_library_menu_lists_remove_and_close_with_tips_and_remove_takes_the_row_away(
    load: Any, controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    _, other = folders
    load()
    open_folders(controller, qtbot, *folders)
    load()
    window, root = load.window, load.window.contentItem()
    index = row(controller, other, "Another Show - S01E01.mkv", up=2)
    menu = _named(window, "libraryMenu")
    _click(window, _row(root, controller.tree.row_id(index)), Qt.MouseButton.RightButton)
    qtbot.waitUntil(lambda: bool(menu.property("visible")))
    entries = {_evaluate(menu, f"itemAt({i})").property("text"): _evaluate(menu, f"itemAt({i})") for i in range(5)}
    assert list(entries) == ["Discard changes", "Exclude", "Add to queue", "Remove from list", "Close folder"]
    assert "not listed at all" in entries["Remove from list"].property("tip")
    assert "out of every run" in entries["Exclude"].property("tip")
    assert "Another Show (2018)" in entries["Close folder"].property("tip")
    _click(window, entries["Remove from list"])
    qtbot.waitUntil(lambda: "Another Show - S01E01.mkv" not in listed(controller))
    assert load() == []


def test_the_home_button_in_the_top_bar_shows_home_and_back_to_the_library_returns(
    load: Any, controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, _ = folders
    load()
    root = load.window.contentItem()
    assert not _visible_named(root, "backToLibrary")  # nothing is open: no way back to offer
    assert not _visible_named(root, "homeButton")
    open_folders(controller, qtbot, show)
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv", up=1))
    load()
    button = _visible(root, "homeButton")
    assert button.property("label") == "Home"
    _click(load.window, button)
    qtbot.waitUntil(lambda: controller.home_shown)
    load()
    assert not button.property("enabled")  # Home already
    back = _visible(root, "backToLibrary")
    _click(load.window, back)
    qtbot.waitUntil(lambda: not controller.home_shown)
    load()
    assert _visible(root, "homeButton").property("enabled")
    assert controller.batch["title"] == "Season 1"
    assert load() == []


def _visible_named(root: Any, name: str) -> list[Any]:
    return [i for i in _all(root) if i.objectName() == name and i.isVisible()]
