"""The pieces QML reads that hold logic: the Theme and Strings objects, the icons, and the text built for a batch."""

from __future__ import annotations

from datetime import datetime

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from showrunner.app.batches.batch import BatchKey
from showrunner.app.library.library import Library
from showrunner.ui.quick.facts import duration, heading, video_summary, when
from showrunner.ui.quick.icons import ICONS, IconProvider, svg_for
from showrunner.ui.quick.strings import Strings
from showrunner.ui.quick.theme import Theme
from showrunner.ui.theme.tokens import QUICK_ROLES, SIZES, Base, ThemeColors, with_base


def test_theme_has_a_property_per_token(qapp: QApplication) -> None:
    theme = Theme()
    assert theme.property("ground") == QColor("#0b0d10")
    assert all(isinstance(theme.property(key), QColor) for key in QUICK_ROLES)
    assert all(theme.property(key) == value for key, value in SIZES.items())
    assert theme.property("font") == "Inter"


def test_theme_tells_qml_when_the_colors_change(qapp: QApplication) -> None:
    theme = Theme()
    heard = []
    theme.changed.connect(lambda: heard.append(True))
    theme.set_colors(with_base(ThemeColors(), Base.PRIMARY, "#ff8fa8"))
    assert heard == [True]
    assert theme.property("control") == QColor("#ff8fa8")


def test_strings_fill_placeholders_and_plurals(qapp: QApplication) -> None:
    strings = Strings()
    assert strings.t("home.get") == "Get it"
    assert strings.f("home.get_named", {"name": "FFmpeg"}) == "Get FFmpeg"
    assert strings.n("time.days", 1) == "1 day ago"
    assert strings.n("time.days", 3) == "3 days ago"
    assert strings.t("no.such.key") == "no.such.key"


def test_icon_ids_are_checked() -> None:
    assert svg_for("search/7e8894") is not None
    assert 'stroke="#7e8894"' in (svg_for("search/7e8894") or "")
    assert svg_for("logo/e7eaee/8fa8ff") is not None
    assert svg_for("search") is None
    assert svg_for("search/zzzzzz") is None
    assert svg_for("nothing/7e8894") is None
    assert svg_for("logo/e7eaee") is None


@pytest.mark.parametrize("name", sorted(ICONS))
def test_every_icon_draws_something(qapp: QApplication, name: str) -> None:
    image = IconProvider().requestImage(f"{name}/ffffff", QSize(), QSize(24, 24))
    assert image.width() == 24
    assert any(image.pixelColor(x, y).alpha() for x in range(24) for y in range(24))


def test_season_heading(library: Library) -> None:
    season = [i for i in library.items if BatchKey.of(i) == BatchKey.of(library.items[0])]
    head = heading(BatchKey.of(season[0]), season)
    assert (head.over, head.title) == ("Show Name (2020)", "Season 1")
    assert head.facts.startswith("10 episodes · 2160p HEVC HDR/DV · ")


def test_show_movie_and_selection_headings(library: Library) -> None:
    show = [i for i in library.items if getattr(i.identity, "show", "") == "Show Name"]
    assert heading(BatchKey.of(show[0], whole_show=True), show).facts.startswith("2 seasons · 18 episodes")
    movie = library.items[-3]
    head = heading(BatchKey.of(movie), [movie])
    assert (head.over, head.title) == ("Movie", "Movie Title")
    assert head.facts.startswith("2021 · 2h 14m · 2160p HEVC HDR · ")
    movies = list(library.items[-3:])
    assert heading(BatchKey.movies(), movies).title == "Movies"
    episode = library.items[2]
    head = heading(BatchKey.file(episode), [episode])
    assert (head.over, head.title) == ("Show Name (2020) · Season 1", "Episode Three")


def test_video_summary_and_duration(library: Library) -> None:
    assert video_summary(library.items[0]) == "2160p HEVC HDR/DV"
    assert duration(45 * 60) == "45m"
    assert duration(134 * 60) == "2h 14m"


@pytest.mark.parametrize(
    ("opened", "expected"),
    [
        ("2026-03-10T09:00:00", "today"),
        ("2026-03-09T23:00:00", "yesterday"),
        ("2026-03-08T10:00:00", "2 days ago"),
        ("2026-03-02T10:00:00", "last week"),
        ("2026-02-20T10:00:00", "2 weeks ago"),
        ("2026-01-20T10:00:00", "last month"),
        ("2025-11-01T10:00:00", "4 months ago"),
        ("2024-01-01T10:00:00", "over a year ago"),
        ("garbage", ""),
    ],
)
def test_when(opened: str, expected: str) -> None:
    assert when(opened, datetime(2026, 3, 10, 12, 0)) == expected
