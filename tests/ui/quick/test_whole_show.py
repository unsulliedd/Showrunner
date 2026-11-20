"""A whole show whose files hold different tracks: a click on a chip changes that chip's tracks and no other, the chip
shows the click at once and says where the plan kept the track, and the chips stay where they are drawn when a plan
arrives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import (
    AudioProperties,
    HdrKind,
    ObjectAudio,
    SubtitleProperties,
    Track,
    TrackFlags,
    TrackKind,
    VideoProperties,
)
from showrunner.ui.quick.window import WindowController

from .conftest import GB, cells
from .test_choices import settle
from .test_qml import _click, _item, _items, _open_lists

SEASONS = 4
PER_SEASON = 12


def _tracks(index: int) -> tuple[Track, ...]:
    """Tracks the way a long release holds them: most files have Dolby Digital 5.1 and an Atmos TrueHD track, some
    only one of them, some a commentary, and the subtitles come and go."""
    video = VideoProperties(3840, 2160, 23.976, HdrKind.NONE, 10)
    tracks = [Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=video)]
    english = Language("eng")
    if index % 10 != 0:  # the files without Dolby Digital 5.1 keep only the TrueHD track
        tracks.append(
            Track(1, TrackKind.AUDIO, "A_AC3", english, "", TrackFlags(default=True), audio=AudioProperties(6))
        )
    if index % 7 != 0:
        atmos = AudioProperties(6, object_audio=ObjectAudio.ATMOS)
        tracks.append(Track(2, TrackKind.AUDIO, "A_TRUEHD", english, "", audio=atmos))
    if index % 5 != 0:
        tracks.append(Track(3, TrackKind.AUDIO, "A_AC3", english, "Commentary", audio=AudioProperties(2)))
    text, picture = SubtitleProperties(), SubtitleProperties(False)
    if index % 3 == 0:
        tracks.append(
            Track(4, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("tur"), "", TrackFlags(default=True), subtitle=text)
        )
    if index % 6 == 0:
        sdh = TrackFlags(hearing_impaired=True)
        tracks.append(Track(5, TrackKind.SUBTITLE, "S_HDMV/PGS", english, "SDH", sdh, subtitle=picture))
    if index % 11 == 0:
        tracks.append(Track(6, TrackKind.SUBTITLE, "S_HDMV/PGS", english, "", subtitle=picture))
    return tuple(tracks)


def whole_show() -> Library:
    items = []
    index = 0
    for season in range(1, SEASONS + 1):
        for number in range(1, PER_SEASON + 1):
            index += 1
            folder = Path("Show Name (2020)") / f"Season {season}"
            stem = f"Show.Name.S{season:02d}E{number:02d}"
            file = MediaFile(folder / f"{stem}.mkv", "matroska", 3134.0, int(6.4 * GB), tracks=_tracks(index))
            paired = (SubtitleFile(folder / f"{stem}.tur.srt", Language("tur")),) if index % 4 else ()
            items.append(MediaItem(Episode("Show Name", season, number, 2020, f"Episode {index}"), file, paired))
    return Library(tuple(items))


@pytest.fixture
def show(controller: WindowController, qtbot: QtBot) -> Library:
    library = whole_show()
    controller.start()
    controller.model.set_library(library)
    first = controller.tree.index_of(str(library.items[0].file.path))
    controller.select(first.parent().parent())
    settle(controller, qtbot)
    return library


def chips(controller: WindowController) -> list[dict[str, Any]]:
    return [c for group in controller.overview["groups"] for c in group["chips"]]


def by_title(controller: WindowController, title: str, name: str = "") -> dict[str, Any]:
    return next(c for c in chips(controller) if title in c["title"] and c["name"] == name)


def label(index: int) -> str:
    """How a whole show names the file that is the `index`-th of the show (counting from 1)."""
    season, number = divmod(index - 1, PER_SEASON)
    return f"S{season + 1:02d}E{number + 1:02d}"


def tracks_kept(controller: WindowController) -> list[list[str]]:
    """Per file, the state of each column's tracks."""
    return [[cell["state"] for cell in row] for row in cells(controller)]


def test_a_chip_drops_at_once_and_keeps_saying_so_where_the_plan_keeps_the_track(
    controller: WindowController, show: Library, qtbot: QtBot
) -> None:
    controller.toggle_keep(by_title(controller, "Dolby Digital 2.0", "Commentary")["id"])
    settle(controller, qtbot)
    truehd = by_title(controller, "TrueHD")
    assert truehd["state"] == "kept"
    controller.toggle_keep(truehd["id"])
    # Before the plan of the whole show arrives, the chip already shows the choice.
    assert controller.planning
    assert by_title(controller, "TrueHD")["state"] == "dropped"
    settle(controller, qtbot)
    # Files with the commentary dropped and no Dolby Digital 5.1 would be left without audio: their plan is refused,
    # so the track stays there, and the chip says in how many files and why.
    clicked = by_title(controller, "TrueHD")
    assert clicked["state"] == "dropped"
    assert clicked["count"] == "missing in 6 files · not dropped in 4 files"
    assert len([r for r in controller.overview["rows"] if "no audio" in r["warning"]]) == 4
    lacking, held = controller.track_missing(clicked["id"]), controller.track_held(clicked["id"])
    assert lacking == "Missing in " + ", ".join(label(n) for n in (7, 14, 21, 28, 35, 42))
    assert held == (
        "Not dropped in "
        + ", ".join(label(n) for n in (10, 20, 30, 40))
        + ". Tracks stay as they are: the choices would leave no audio"
    )
    # A second click gives the track back: the chip said it was dropped.
    controller.toggle_keep(clicked["id"])
    settle(controller, qtbot)
    again = by_title(controller, "TrueHD")
    assert (again["state"], again["count"]) == ("kept", "missing in 6 files")


def test_a_click_changes_the_tracks_of_the_chip_clicked_and_no_other(
    controller: WindowController, show: Library, qtbot: QtBot
) -> None:
    """Only a file whose plan the click makes refused (it would be left without audio) goes back to its tracks as
    they are, and that file says so in its row."""
    for dropped_first in (None, "Commentary"):
        if dropped_first:
            controller.toggle_keep(by_title(controller, "Dolby Digital 2.0", dropped_first)["id"])
            settle(controller, qtbot)
        for chip in chips(controller):
            before = tracks_kept(controller)
            controller.toggle_keep(chip["id"])
            settle(controller, qtbot)
            after = tracks_kept(controller)
            for old, new, row in zip(before, after, controller.overview["rows"], strict=True):
                changed = {column for column, (a, b) in enumerate(zip(old, new, strict=True)) if a != b}
                assert changed <= {chip["id"]} or row["warning"], (chip["code"], chip["title"], row["title"], changed)
            controller.toggle_keep(chip["id"])  # and back
            settle(controller, qtbot)
            assert tracks_kept(controller) == before


def test_a_refused_file_tells_the_chip_of_every_track_it_keeps_though_dropped(
    controller: WindowController, show: Library, qtbot: QtBot
) -> None:
    commentary = by_title(controller, "Dolby Digital 2.0", "Commentary")
    controller.toggle_keep(commentary["id"])
    settle(controller, qtbot)
    assert by_title(controller, "Dolby Digital 2.0", "Commentary")["count"] == "missing in 9 files"
    # The files with no TrueHD would be left without audio: all their tracks stay, the commentary too.
    controller.toggle_keep(by_title(controller, "Dolby Digital 5.1")["id"])
    settle(controller, qtbot)
    assert by_title(controller, "Dolby Digital 5.1")["count"] == "missing in 4 files · not dropped in 6 files"
    assert by_title(controller, "Dolby Digital 2.0", "Commentary")["count"] == (
        "missing in 9 files · not dropped in 5 files"
    )


def _scene(item: QQuickItem) -> QPointF:
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2))


def test_chips_and_their_scroll_stay_where_they_are_drawn_when_a_plan_arrives(
    load: Any, controller: WindowController, show: Library, qtbot: QtBot
) -> None:
    load()
    root = load.window.contentItem()
    chip = _item(root, "chip1")
    _click(load.window, _item(chip, "namesButton"))
    load()
    flick = _item(root, "chipGroups").property("contentItem")
    flick.setProperty("contentY", 60)
    (rows,) = _open_lists(root)
    rows.setProperty("contentY", 100)
    load()
    chip.setProperty("marker", 7)
    where = {c["id"]: _scene(_item(root, f"chip{c['id']}")) for c in chips(controller)}
    controller.toggle_flag(0, "default")  # a choice: the view is built again, then the plan arrives
    for _ in range(3):
        settle(controller, qtbot)
        load()
    # The same delegates, updated in place: nothing the user aimed at moves to make another chip take the click.
    assert _item(root, "chip1").property("marker") == 7
    assert flick.property("contentY") == 60
    assert _open_lists(root)[0].property("contentY") == 100
    assert {c["id"]: _scene(_item(root, f"chip{c['id']}")) for c in chips(controller)} == where
    assert load() == []


def test_a_click_inside_the_foldout_never_keeps_or_drops(
    load: Any, controller: WindowController, show: Library, qtbot: QtBot
) -> None:
    load()
    root = load.window.contentItem()
    chip = _item(root, "chip1")
    _click(load.window, _item(chip, "namesButton"))
    load()
    (rows,) = _open_lists(root)
    # On a row, on the line for the missing files, in the room around the list and on the frame's lower edge.
    spots = [(0.5, 0.05), (0.5, 0.5), (0.2, 0.95), (0.9, 0.5)]
    points = [rows.mapToScene(QPointF(rows.width() * x, rows.height() * y)) for x, y in spots]
    points += [rows.mapToScene(QPointF(4, rows.height() + 4)), rows.mapToScene(QPointF(rows.width() + 4, 20))]
    for point in points:
        QTest.mouseClick(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point.toPoint())
        load()
    assert controller.rules == []
    assert len(_open_lists(root)) == 1
    # Nor does the rest of the row: only its box keeps or drops.
    header = _item(chip, "chipHeader")
    QTest.mouseClick(
        load.window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        header.mapToScene(QPointF(header.width() / 2, header.height() / 2)).toPoint(),
    )
    load()
    assert controller.rules == []
    _click(load.window, _item(chip, "keepBox"))
    load()
    assert len(controller.rules) == 1
    assert _items(root, "chipNameRows")


def test_the_foldout_of_a_dropped_chip_says_first_where_the_plan_keeps_the_track(
    load: Any, controller: WindowController, show: Library, qtbot: QtBot
) -> None:
    controller.toggle_keep(by_title(controller, "Dolby Digital 2.0", "Commentary")["id"])
    settle(controller, qtbot)
    controller.toggle_keep(by_title(controller, "TrueHD")["id"])
    settle(controller, qtbot)
    load()
    root = load.window.contentItem()
    chip = _item(root, "chip1")
    _click(load.window, _item(chip, "namesButton"))
    load()
    assert chip.property("held").startswith("Not dropped in S01E10, S02E08")
    assert chip.property("missing").startswith("Missing in S01E07")
    (rows,) = _open_lists(root)
    assert rows.property("contentY") == -rows.property("headerItem").height()  # the list starts with the reason
    assert load() == []
