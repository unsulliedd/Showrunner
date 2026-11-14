"""The Naming page: the four templates with what each makes of the selected file, the token picker, the user's own
tokens and the value maps. Edits go to the working copy of the active profile."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.jobs.blocked import TITLE_TEMPLATE, TRACK_TEMPLATES, template_problems
from showrunner.app.settings.app_settings import load_settings, save_settings
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.core.naming import (
    TOKENS,
    CustomKind,
    CustomToken,
    NamingContext,
    NamingOptions,
    Scope,
    check_tokens,
    preview,
)
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.tracks import PlanRefused, TracksOptions, plan_tracks
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.settings.messages import problem_text, template_problem
from showrunner.ui.settings.page import ProfileFooter, SettingsPage, clear_layout, heading, label, link_button
from showrunner.ui.settings.problem_field import ProblemEditor, ProblemField
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.sheet.format import item_title
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.qt_theme import build_mono_font
from showrunner.ui.theme.tokens import SIZES

_log = logging.getLogger(__name__)

SOURCES = ("BluRay", "WEB-DL", "WEBRip", "HDTV", "DVD", "Hybrid WEB-DL")
_KINDS = dict(zip(TRACK_TEMPLATES, (TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.SUBTITLE), strict=True))
_TEMPLATE_KEYS = {TITLE_TEMPLATE: "title", **{t: t.split("_")[0] for t in TRACK_TEMPLATES}}
NAME_ROLE = Qt.ItemDataRole.UserRole + 1

# Stands in for a selected file, so the previews show something before a library is loaded.
SAMPLE_ITEM = MediaItem(
    Episode("Show Name", 1, 5, 2020, "Episode Five"),
    MediaFile(
        Path("Show Name (2020) - 1x05 - Episode Five.mkv"),
        "matroska",
        tracks=(
            Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080, 23.976, bit_depth=10)),
            Track(1, TrackKind.AUDIO, "A_EAC3", Language("eng"), audio=AudioProperties(6)),
            Track(2, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties()),
        ),
    ),
)


class NamingPage(SettingsPage):
    """`source_changed` carries the batch's source, kept with the workspace rather than the profile."""

    source_changed = Signal(str)

    def __init__(self, session: ProfileSession, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(tr("settings.page.naming"), tr("settings.naming.lead"), parent=parent)
        self._session = session
        self._theme = theme
        self._item: MediaItem | None = None
        self._source = load_settings().value.batch_source
        self._last_field: ProblemField | None = None

        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.addItem(tr("settings.naming.source_guess"))
        self.source.addItems(SOURCES)
        self.source.setCurrentText(self._source or tr("settings.naming.source_guess"))
        self.source.currentTextChanged.connect(self._on_source)
        self.set_names = QCheckBox(tr("settings.naming.set_names"))
        self.set_names.toggled.connect(lambda on: session.update("naming", enabled=on))
        self.title_row.addWidget(label(tr("settings.naming.source"), "muted"), 0, Qt.AlignmentFlag.AlignTop)
        self.title_row.addWidget(self.source, 0, Qt.AlignmentFlag.AlignTop)
        self.title_row.addWidget(self.set_names, 0, Qt.AlignmentFlag.AlignTop)

        columns = QHBoxLayout()
        columns.setSpacing(SIZES["space_xl"])
        left = QVBoxLayout()
        left.setSpacing(SIZES["space_sm"])
        self.preview_on = label(role="preview_strip", wrap=True)
        left.addWidget(self.preview_on)
        left.addSpacing(SIZES["space_md"])
        left.addWidget(heading(tr("settings.naming.templates")))
        self.editors: dict[str, ProblemEditor] = {}
        self.previews: dict[str, QVBoxLayout] = {}
        for template, key in _TEMPLATE_KEYS.items():
            caption = QHBoxLayout()
            caption.setSpacing(SIZES["space_md"])
            name = label(tr(f"settings.naming.{key}"))
            name.setProperty("heading", True)
            caption.addWidget(name)
            if key == "title":
                caption.addWidget(label(tr("settings.naming.title_help"), "muted", size="sm"))
            caption.addStretch()
            left.addSpacing(SIZES["space_sm"])
            left.addLayout(caption)
            editor = ProblemEditor(theme)
            editor.field.edited.connect(lambda text, t=template: self._set_template(t, text))
            editor.field.focused.connect(lambda f=editor.field: self._remember_field(f))
            self.editors[template] = editor
            left.addWidget(editor)
            lines = QVBoxLayout()
            lines.setContentsMargins(SIZES["space_md"], SIZES["space_xs"], 0, 0)
            lines.setSpacing(SIZES["space_xs"])
            self.previews[template] = lines
            left.addLayout(lines)

        left.addSpacing(SIZES["space_lg"])
        left.addLayout(self._table_heading("custom", "add_token", self._add_token, self._remove_token))
        self.tokens = self._table(["name", "kind", "definition", "value"])
        self.tokens.itemChanged.connect(lambda _item: QTimer.singleShot(0, self._tokens_edited))
        left.addWidget(self.tokens)
        self.token_problems = QVBoxLayout()
        left.addLayout(self.token_problems)
        left.addWidget(label(tr("settings.naming.custom_help"), "muted", wrap=True, size="sm"))
        left.addSpacing(SIZES["space_lg"])
        left.addLayout(self._table_heading("maps", "add_map", self._add_map, self._remove_map))
        self.maps = self._table(["token", "value_read", "write_instead"])
        self.maps.itemChanged.connect(lambda _item: QTimer.singleShot(0, self._maps_edited))
        left.addWidget(self.maps)
        left.addStretch()
        columns.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(SIZES["space_md"])
        picker = QWidget()
        picker.setFixedWidth(SIZES["token_picker_width"])
        picker.setLayout(right)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(heading(tr("settings.naming.tokens")))
        self.find = QLineEdit()
        self.find.setPlaceholderText(tr("settings.naming.find_token"))
        self.find.setClearButtonEnabled(True)
        right.addWidget(self.find)
        self.token_model = QStandardItemModel(0, 2, self)
        self.token_filter = QSortFilterProxyModel(self)
        self.token_filter.setSourceModel(self.token_model)
        self.token_filter.setRecursiveFilteringEnabled(True)
        self.token_filter.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.find.textChanged.connect(self.token_filter.setFilterFixedString)
        self.picker = QTreeView()
        self.picker.setProperty("role", "tokens")
        self.picker.setModel(self.token_filter)
        self.picker.setHeaderHidden(True)
        self.picker.setRootIsDecorated(False)
        self.picker.setIndentation(SIZES["space_md"])
        self.picker.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.picker.doubleClicked.connect(self._insert_token)
        self.picker.activated.connect(self._insert_token)
        self.picker.header().setStretchLastSection(False)
        self.picker.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.picker.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        right.addWidget(self.picker, 1)
        for key in ("insert_hint", "group_hint", "escape_hint"):
            right.addWidget(label(tr(f"settings.naming.{key}"), "muted", wrap=True, size="sm"))
        columns.addWidget(picker)
        self.body.addLayout(columns)

        self.footer = ProfileFooter(session, self._footer_problems)
        self.add_footer(self.footer)
        session.changed.connect(self.refresh)
        self.refresh()

    # Building blocks

    def _table_heading(self, key: str, add: str, on_add, on_remove) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(heading(tr(f"settings.naming.{key}")))
        row.addStretch()
        row.addWidget(link_button(tr("settings.naming.remove"), on_remove))
        row.addWidget(link_button(tr(f"settings.naming.{add}"), on_add))
        return row

    @staticmethod
    def _table(columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setProperty("role", "settings_table")
        table.setHorizontalHeaderLabels([tr(f"settings.naming.col.{c}") for c in columns])
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(SIZES["height_md"] + SIZES["space_sm"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setFont(build_mono_font())
        return table

    @staticmethod
    def _fit(table: QTableWidget) -> None:
        rows = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(table.horizontalHeader().sizeHint().height() + rows + SIZES["space_xs"])

    # Inputs from the window

    def set_item(self, item: MediaItem | None) -> None:
        self._item = item
        self.refresh()

    @property
    def naming(self) -> NamingOptions:
        return self._session.options("naming")

    def _context(self, track: Track | None = None) -> NamingContext:
        naming = self.naming
        tracks: TracksOptions = self._session.options("tracks")
        return NamingContext(
            self._item or SAMPLE_ITEM,
            track,
            self._source,
            naming.custom_tokens,
            naming.value_maps,
            flags_from_names=tracks.flags_from_names,
        )

    def _names(self) -> list[str]:
        return [*TOKENS, *(t.name for t in self.naming.custom_tokens)]

    # Showing the options

    def refresh(self) -> None:
        naming = self.naming
        item = self._item or SAMPLE_ITEM
        self.preview_on.setText(
            tr("settings.naming.preview_on", name=item_title(item))
            if self._item
            else tr("settings.naming.preview_sample")
        )
        self.set_names.blockSignals(True)
        self.set_names.setChecked(naming.enabled)
        self.set_names.blockSignals(False)
        names = self._names()
        for template, editor in self.editors.items():
            editor.field.set_text(getattr(naming, template))
            editor.set_problems([template_problem(p, names) for p in template_problems(naming, template)])
            self._show_preview(template)
        self._show_tokens()
        self._show_maps()
        self._show_picker()

    def _show_preview(self, template: str) -> None:
        lines = self.previews[template]
        clear_layout(lines)
        text = getattr(self.naming, template)
        if template == TITLE_TEMPLATE:
            lines.addWidget(label(preview(text, self._context()).text or tr("common.none")))
            return
        item = self._item or SAMPLE_ITEM
        plan = plan_tracks(item, self._session.options("tracks"))
        kept = (
            [(t, None) for t in item.file.tracks]
            if isinstance(plan, PlanRefused)
            else [(replace(k.track, flags=k.flags), k.external) for k in plan.kept]
        )
        for track, external in kept:
            if track.kind is not _KINDS[template]:
                continue
            row = QHBoxLayout()
            row.setSpacing(SIZES["space_md"])
            number = label("+" if external is not None else str(track.id), "muted")
            number.setFixedWidth(SIZES["height_sm"])
            row.addWidget(number)
            name = preview(text, self._context(track)).text or tr("common.none")
            if external is not None:
                name = tr("settings.naming.added_from", name=name, file=external.path.name)
            row.addWidget(label(name), 1)
            lines.addLayout(row)

    def _show_tokens(self) -> None:
        table = self.tokens
        table.blockSignals(True)
        table.setRowCount(0)
        for token in self.naming.custom_tokens:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(token.name))
            kind = QComboBox()
            for value in CustomKind:
                kind.addItem(tr(f"settings.naming.kind.{value.value}"), value.value)
            kind.setCurrentIndex(kind.findData(token.kind.value))
            # Later, not now: the update rebuilds the table, and with it this combo box.
            kind.currentIndexChanged.connect(lambda _i: QTimer.singleShot(0, self._tokens_edited))
            table.setCellWidget(row, 1, kind)
            table.setItem(row, 2, QTableWidgetItem(token.text))
            value = preview(f"{{{token.name}}}", self._context()).text if token.name else ""
            shown = QTableWidgetItem(value or tr("common.none"))
            shown.setFlags(shown.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 3, shown)
        table.blockSignals(False)
        self._fit(table)
        clear_layout(self.token_problems)
        for problem in check_tokens(self.naming.custom_tokens, self.naming.value_maps):
            text = problem_text(problem.problem.kind, problem.problem.detail)
            self.token_problems.addWidget(label(f"{problem.name}: {text}", "danger", wrap=True, size="sm"))

    def _show_maps(self) -> None:
        table = self.maps
        table.blockSignals(True)
        table.setRowCount(0)
        for token, values in self.naming.value_maps.items():
            for read, written in values.items():
                row = table.rowCount()
                table.insertRow(row)
                for column, text in enumerate((token, read, written)):
                    table.setItem(row, column, QTableWidgetItem(text))
        table.blockSignals(False)
        self._fit(table)

    def _show_picker(self) -> None:
        model = self.token_model
        model.removeRows(0, model.rowCount())
        item = self._item or SAMPLE_ITEM
        track = next(iter(item.file.audio_tracks), None) or next(iter(item.file.tracks), None)
        groups = {
            Scope.ITEM: tr("settings.naming.group.item"),
            Scope.VIDEO: tr("settings.naming.group.video"),
            Scope.TRACK: tr(
                "settings.naming.group.track",
                track=tr(f"settings.naming.kind_track.{track.kind.value}", id=track.id) if track else "",
            ),
        }
        mono = build_mono_font()

        def add(group: str, names: list[str]) -> None:
            parent = QStandardItem(group)
            parent.setSelectable(False)
            model.appendRow([parent, QStandardItem()])
            for name in names:
                value = preview(f"{{{name}}}", self._context(track)).text
                cell = QStandardItem(f"{{{name}}}")
                cell.setFont(mono)
                cell.setData(name, NAME_ROLE)
                shown = QStandardItem(value or tr("common.none"))
                shown.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                shown.setForeground(self.palette().placeholderText())
                parent.appendRow([cell, shown])

        for scope, title in groups.items():
            add(title, [t.name for t in TOKENS.values() if t.scope is scope])
        if self.naming.custom_tokens:
            add(tr("settings.naming.group.custom"), [t.name for t in self.naming.custom_tokens if t.name])
        self.picker.expandAll()

    def _footer_problems(self) -> str:
        block = self._session.blocks().get("metadata")
        return tr_plural("settings.naming.footer_problems", block.count) if block else ""

    # Edits

    def _remember_field(self, field: ProblemField) -> None:
        self._last_field = field

    def _insert_token(self, index: QModelIndex) -> None:
        name = index.siblingAtColumn(0).data(NAME_ROLE)
        field = self._last_field or self.editors[TITLE_TEMPLATE].field
        if name:
            field.insert(f"{{{name}}}")

    def _set_template(self, template: str, text: str) -> None:
        self._session.update("naming", **{template: text})

    def _on_source(self, text: str) -> None:
        source = "" if text == tr("settings.naming.source_guess") else text.strip()
        if source == self._source:
            return
        self._source = source
        try:
            save_settings(replace(load_settings().value, batch_source=source))
        except OSError:
            _log.exception("Could not save the source")
        self.source_changed.emit(source)
        self.refresh()

    def _tokens_edited(self) -> None:
        tokens = []
        for row in range(self.tokens.rowCount()):
            kind = self.tokens.cellWidget(row, 1)
            old = self.naming.custom_tokens[row] if row < len(self.naming.custom_tokens) else CustomToken()
            tokens.append(
                CustomToken(
                    self.tokens.item(row, 0).text().strip(),
                    CustomKind(kind.currentData()) if kind else CustomKind.CONSTANT,
                    self.tokens.item(row, 2).text(),
                    old.source,
                )
            )
        self._session.update("naming", custom_tokens=tokens)

    def _add_token(self) -> None:
        name = f"token_{len(self.naming.custom_tokens) + 1}"
        self._session.update("naming", custom_tokens=[*self.naming.custom_tokens, CustomToken(name)])

    def _remove_token(self) -> None:
        row = self.tokens.currentRow()
        if row >= 0:
            tokens = [t for n, t in enumerate(self.naming.custom_tokens) if n != row]
            self._session.update("naming", custom_tokens=tokens)

    def _maps_edited(self) -> None:
        maps: dict[str, dict[str, str]] = {}
        for row in range(self.maps.rowCount()):
            token, read, written = (self.maps.item(row, c).text().strip() for c in range(3))
            if token:
                maps.setdefault(token, {})[read] = written
        self._session.update("naming", value_maps=maps)

    def _add_map(self) -> None:
        maps = {k: dict(v) for k, v in self.naming.value_maps.items()}
        maps.setdefault("codec", {})[tr("settings.naming.new_value")] = ""
        self._session.update("naming", value_maps=maps)

    def _remove_map(self) -> None:
        row = self.maps.currentRow()
        if row < 0:
            return
        token, read = self.maps.item(row, 0).text(), self.maps.item(row, 1).text()
        maps = {k: {r: w for r, w in v.items() if (k, r) != (token, read)} for k, v in self.naming.value_maps.items()}
        self._session.update("naming", value_maps={k: v for k, v in maps.items() if v})
