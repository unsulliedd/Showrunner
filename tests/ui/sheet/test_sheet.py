from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from showrunner.app.library.library import Library
from showrunner.ui.sheet.format import duration_text, size_text, track_summary
from showrunner.ui.sheet.sheet import Sheet
from showrunner.ui.sheet.tracks import FLAGS_COLUMN, FLAGS_ROLE, TrackModel, TracksView
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES


@pytest.fixture
def sheet(qapp: QApplication, theme: ThemeManager) -> Sheet:
    sheet = Sheet(theme)
    sheet.resize(1000, 600)
    sheet.show()
    return sheet


def path_of(library: Library, name: str) -> Path:
    return next(i.file.path for i in library.items if name in i.file.path.name)


def buttons(widget: QWidget, text: str) -> list[QPushButton]:
    return [b for b in widget.findChildren(QPushButton) if b.text() == text]


def test_a_video_shows_title_state_tracks_chapters_and_attachments(sheet: Sheet, sample_library: Library) -> None:
    sheet.show_item(sample_library, path_of(sample_library, "S01E01"))
    assert sheet.title.text() == "Alpha S01E01 · Pilot"
    assert sheet.path_label.toolTip() == str(Path("lib/Alpha/S01/Alpha S01E01.mkv"))
    assert sheet.meta_label.text() == "952 MB · 22:07"
    assert sheet.state.text() == ""
    assert sheet.splitter.isVisible()
    tracks = sheet.sections.widget().findChild(TracksView)
    assert tracks is not None
    assert tracks.model().rowCount() == 3
    assert tracks.height() >= 6 * SIZES["row_md"]


def test_the_state_names_an_unsure_pairing_and_a_file_that_could_not_be_read(
    sheet: Sheet, sample_library: Library
) -> None:
    sheet.show_item(sample_library, path_of(sample_library, "S01E02"))
    assert sheet.state.text() == "Pairing unsure"
    assert sheet.state.property("role") == "notice"
    sheet.show_item(sample_library, path_of(sample_library, "Beta"))
    assert sheet.state.text() == "Could not be read"
    assert sheet.state.toolTip() == "broken header"
    assert sheet.state.property("role") == "danger"


def test_tracks_are_grouped_by_kind_with_flags_as_chips(qapp: QApplication, sample_library: Library) -> None:
    model = TrackModel(sample_library.items[0].file)
    groups = [model.index(r, 0).data() for r in range(model.rowCount())]
    assert groups == ["Video 1", "Audio 1", "Subtitles 1"]
    audio = model.index(0, 0, model.index(1, 0))
    assert [model.index(audio.row(), c, audio.parent()).data() for c in range(4)] == [
        "1",
        "eng",
        "AC-3 · 5.1",
        "AC-3 5.1",
    ]
    assert model.index(audio.row(), FLAGS_COLUMN, audio.parent()).data(FLAGS_ROLE) == ["Default"]
    subtitle = model.index(0, FLAGS_COLUMN, model.index(2, 0))
    assert subtitle.data(FLAGS_ROLE) == ["Forced"]


def test_the_codec_line_depends_on_the_kind_of_track(sample_library: Library) -> None:
    video, audio, subtitle = sample_library.items[0].file.tracks
    assert track_summary(video) == "HEVC · 1080p · 10-bit · 23.976 fps"
    assert track_summary(audio) == "AC-3 · 5.1"
    assert track_summary(subtitle) == "SubRip · text"


def test_sizes_and_durations_read_short() -> None:
    assert size_text(214_000) == "214 KB"
    assert size_text(6_840_000_000) == "6.84 GB"
    assert size_text(12) == "12 B"
    assert duration_text(49 * 60 + 12) == "49:12"
    assert duration_text(3600 + 61) == "1:01:01"


def test_a_file_that_was_not_read_says_so_instead_of_an_empty_table(sheet: Sheet, sample_library: Library) -> None:
    bare = replace(sample_library.items[2], file=replace(sample_library.items[2].file, tracks=(), chapters=()))
    library = replace(sample_library, items=(bare,), alternatives=(), failures=())
    sheet.show_item(library, bare.file.path)
    labels = [label.text() for label in sheet.sections.widget().findChildren(QLabel)]
    assert "The tracks have not been read." in labels


def test_the_details_offer_unpair_pair_instead_and_pair_here(sheet: Sheet, sample_library: Library) -> None:
    first = path_of(sample_library, "S01E01")
    unpair: list[object] = []
    sheet.unpair_requested.connect(unpair.append)
    sheet.show_item(sample_library, first)
    (button,) = buttons(sheet.details, "Unpair")
    button.click()
    assert unpair == [sample_library.item(first).subtitles[0]]
    pair_here: list[tuple[object, object]] = []
    sheet.pair_here_requested.connect(lambda s, v: pair_here.append((s, v)))
    (button,) = buttons(sheet.details, "Pair here")
    button.click()
    assert pair_here == [(sample_library.unpaired[0], first)]

    second = path_of(sample_library, "S01E02")
    instead: list[tuple[object, object]] = []
    sheet.pair_instead_requested.connect(lambda v, s: instead.append((v, s)))
    sheet.show_item(sample_library, second)
    (button,) = buttons(sheet.details, "Pair instead")
    button.click()
    assert instead == [(second, sample_library.alternatives_of(second)[0])]


def test_a_show_or_season_shows_its_counts_and_its_unpaired_files(sheet: Sheet, sample_library: Library) -> None:
    paths = [path_of(sample_library, "S01E01"), path_of(sample_library, "S01E02")]
    sheet.show_group("Season 1", sample_library, paths)
    assert sheet.title.text() == "Season 1"
    assert sheet.path_label.toolTip() == "2 videos · 1 unsure pairing · 1 unpaired subtitle"
    assert not sheet.splitter.isVisible()
    assert sheet.group_area.isVisible()
    pair_to = buttons(sheet.group_area, "Pair to…")
    assert len(pair_to) == 1
    chosen: list[tuple[object, object]] = []
    sheet.pair_here_requested.connect(lambda s, v: chosen.append((s, v)))
    pair_to[0].menu().actions()[1].trigger()
    assert chosen == [(sample_library.unpaired[0], paths[1])]


def test_nothing_selected_shows_a_hint(sheet: Sheet) -> None:
    sheet.show_placeholder()
    assert not sheet.title_row.isVisible()
    assert sheet.group_area.isVisible()
