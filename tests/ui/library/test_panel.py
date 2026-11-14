from __future__ import annotations

import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication

from showrunner.app.library.library import Library
from showrunner.ui.library.model import LibraryModel
from showrunner.ui.library.panel import LibraryPanel
from showrunner.ui.theme.manager import ThemeManager


@pytest.fixture
def panel(qapp: QApplication, theme: ThemeManager, sample_library: Library) -> LibraryPanel:
    model = LibraryModel()
    model.set_library(sample_library)
    return LibraryPanel(model, theme)


def shown(panel: LibraryPanel, parent: QModelIndex | None = None) -> list[str]:
    """Every row that passes the filters, depth first."""
    parent = QModelIndex() if parent is None else parent
    names = []
    for row in range(panel.proxy.rowCount(parent)):
        index = panel.proxy.index(row, 0, parent)
        names.append(index.data())
        names += shown(panel, index)
    return names


def test_without_a_filter_every_row_is_shown(panel: LibraryPanel) -> None:
    assert len(shown(panel)) == 11


def test_the_name_filter_keeps_a_match_with_its_season_and_show(panel: LibraryPanel) -> None:
    panel.filter_edit.setText("second")
    assert shown(panel) == ["Alpha", "Season 1", "02  Second"]


def test_the_name_filter_is_not_case_sensitive_and_ignores_surrounding_spaces(panel: LibraryPanel) -> None:
    panel.filter_edit.setText("  MOVIE TITLE ")
    assert shown(panel) == ["Movies", "Movie Title (2016)"]


def test_a_filter_that_matches_a_show_keeps_everything_below_it(panel: LibraryPanel) -> None:
    panel.filter_edit.setText("beta")
    assert shown(panel) == ["Beta", "Season 1", "01"]


def test_needs_a_look_keeps_only_marked_videos_and_their_parents(panel: LibraryPanel) -> None:
    panel.needs_look.setChecked(True)
    assert shown(panel) == ["Alpha", "Season 1", "02  Second", "Beta", "Season 1", "01"]


def test_both_filters_work_together(panel: LibraryPanel) -> None:
    panel.needs_look.setChecked(True)
    panel.filter_edit.setText("second")
    assert shown(panel) == ["Alpha", "Season 1", "02  Second"]
    panel.needs_look.setChecked(False)
    panel.filter_edit.setText("")
    assert len(shown(panel)) == 11


def test_the_button_counts_the_videos_that_need_a_look(panel: LibraryPanel) -> None:
    assert panel.needs_look.text() == "Needs a look 2"


def test_by_default_shows_are_open_and_the_season_with_a_mark_is_too(panel: LibraryPanel) -> None:
    panel.expand_default()
    expanded = [
        panel.proxy.index(r, 0).data()
        for r in range(panel.proxy.rowCount())
        if panel.tree.isExpanded(panel.proxy.index(r, 0))
    ]
    assert expanded == ["Alpha", "Beta", "Movies"]
    alpha = panel.proxy.index(0, 0)
    assert panel.tree.isExpanded(panel.proxy.index(0, 0, alpha))
    assert not panel.tree.isExpanded(panel.proxy.index(1, 0, alpha))


def test_selecting_a_row_reports_it_as_an_index_of_the_model(panel: LibraryPanel, sample_library: Library) -> None:
    seen: list[QModelIndex] = []
    panel.selection_changed.connect(seen.append)
    target = panel._model.index_for_path(sample_library.items[1].file.path)
    panel.select(target)
    assert panel.current_source_index() == target
    assert seen[-1] == target
