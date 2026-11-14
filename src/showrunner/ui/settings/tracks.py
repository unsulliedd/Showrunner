"""The Track rules page: the ordered rule list, the editor of the selected rule, and what the rules do to the file
selected in the main window."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.track import Track
from showrunner.stages.tracks import (
    NO_LANGUAGE,
    DroppedTrack,
    FlagShape,
    FlagTest,
    KindTest,
    PlanRefused,
    RuleField,
    RuleProblem,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
    check_rules,
    matches,
    plan_tracks,
)
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.marks import dot_icon
from showrunner.ui.settings.messages import rule_problem
from showrunner.ui.settings.page import (
    ProfileFooter,
    Segmented,
    SettingsPage,
    heading,
    label,
)
from showrunner.ui.settings.problem_field import ProblemEditor, entry_spans, split_entries
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.sheet.format import item_title, language_code, track_summary
from showrunner.ui.sheet.tracks import flag_names
from showrunner.ui.sheet.widgets import FitTreeView
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

FLAG_TESTS = ("default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original")
_RESULT_COLUMNS = ("id", "kind", "language", "track", "outcome", "flags")


def rule_summary(rule: TrackRule) -> str:
    """`Audio · tur, eng · commentary`: what the rule matches, in a few words."""
    match = rule.match
    parts = [tr(f"settings.tracks.kind.{match.kind.value}")]
    if match.languages:
        parts.append(", ".join(match.languages))
    if match.codecs:
        parts.append(", ".join(match.codecs))
    if match.min_channels or match.max_channels:
        parts.append(tr("settings.tracks.channels_short", low=match.min_channels or "", high=match.max_channels or ""))
    for flag in FLAG_TESTS:
        test = getattr(match, flag)
        if test is not FlagTest.ANY:
            name = tr(f"settings.tracks.flag.{flag}").casefold()
            parts.append(name if test is FlagTest.SET else tr("settings.tracks.not_flag", flag=name))
    if match.name:
        parts.append(f"“{match.name}”")
    return " · ".join(parts)


def rule_name(index: int, rule: TrackRule) -> str:
    return tr("settings.tracks.rule_named", number=index + 1, label=rule.label or rule_summary(rule))


def dropped_text(drop: DroppedTrack, *, would: bool = False) -> str:
    by_name = not matches(drop.rule.match, drop.track, flags_from_name=False)
    text = tr(
        "settings.tracks.result.would_drop" if would else "settings.tracks.result.dropped_by",
        rule=rule_name(drop.rule_index, drop.rule),
    )
    return text + tr("settings.tracks.result.by_name") if by_name else text


class TracksPage(SettingsPage):
    def __init__(self, session: ProfileSession, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(tr("settings.page.tracks"), tr("settings.tracks.lead"), parent=parent)
        self._session = session
        self._theme = theme
        self._item: MediaItem | None = None
        self._loading = False

        self.use = QCheckBox(tr("settings.tracks.use"))
        self.use.toggled.connect(lambda on: session.update("tracks", enabled=on))
        self.title_row.addWidget(self.use, 0, Qt.AlignmentFlag.AlignTop)

        columns = QHBoxLayout()
        columns.setSpacing(SIZES["space_xl"])
        left = QVBoxLayout()
        left.setSpacing(SIZES["space_md"])
        self.list = QListWidget()
        self.list.setProperty("role", "rules")
        self.list.setFixedWidth(SIZES["rule_list_width"])
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setIconSize(QSize(SIZES["mark_size"] * 2, SIZES["mark_size"] * 2))
        self.list.currentRowChanged.connect(lambda _row: self._show_rule())
        self.list.itemChanged.connect(lambda _item: QTimer.singleShot(0, self._list_edited))
        self.list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._list_edited))
        left.addWidget(self.list, 1)
        # Two rows, so the buttons stay within the list's width and leave the editor its room.
        for row in (
            (("add_rule", self._add), ("move_up", lambda: self._move(-1)), ("move_down", lambda: self._move(1))),
            (("duplicate", self._duplicate), ("delete", self._delete)),
        ):
            buttons = QHBoxLayout()
            buttons.setSpacing(SIZES["space_sm"])
            for key, slot in row:
                button = QPushButton(tr(f"settings.tracks.{key}"))
                button.clicked.connect(lambda _=False, s=slot: s())
                buttons.addWidget(button)
            buttons.addStretch()
            left.addLayout(buttons)
        self.from_names = QCheckBox(tr("settings.tracks.flags_from_names"))
        self.from_names.toggled.connect(lambda on: session.update("tracks", flags_from_names=on))
        left.addWidget(self.from_names)
        left.addWidget(label(tr("settings.tracks.flags_from_names_help"), "muted", wrap=True, size="sm"))
        columns.addLayout(left)
        columns.addWidget(self._build_editor(), 1)
        self.body.addLayout(columns)

        result_head = QHBoxLayout()
        self.result_title = heading("")
        result_head.addWidget(self.result_title)
        result_head.addStretch()
        result_head.addWidget(label(tr("settings.tracks.result.note"), "muted", size="sm"))
        self.body.addSpacing(SIZES["space_lg"])
        self.body.addLayout(result_head)
        self.strip = label(wrap=True)
        self.body.addWidget(self.strip)
        self.result = FitTreeView("tracks")
        self.result_model = QStandardItemModel(0, len(_RESULT_COLUMNS), self)
        self.result.setModel(self.result_model)
        self.body.addWidget(self.result)
        self.remux = label(wrap=True, size="sm")
        self.body.addWidget(self.remux)
        self.body.addStretch()

        self.footer = ProfileFooter(session, self._footer_problems)
        self.add_footer(self.footer)
        session.changed.connect(self.refresh)
        self.refresh()

    # The editor

    def _build_editor(self) -> QWidget:
        editor = QWidget()
        # The page does not scroll sideways, so the editor takes the width left beside the list and no more.
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        form = QFormLayout(editor)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(SIZES["space_lg"])
        form.setVerticalSpacing(SIZES["space_md"])
        top = QHBoxLayout()
        self.rule_title = heading("")
        self.rule_on = QCheckBox(tr("settings.tracks.on"))
        self.rule_on.toggled.connect(lambda on: self._edit(enabled=on))
        top.addWidget(self.rule_title, 1)
        top.addWidget(self.rule_on)
        form.addRow(top)
        self.label_field = QLineEdit()
        self.label_field.editingFinished.connect(lambda: self._edit(label=self.label_field.text().strip()))
        form.addRow(tr("settings.tracks.label"), self.label_field)
        form.addRow(heading(tr("settings.tracks.match")))
        self.kind = Segmented([(k.value, tr(f"settings.tracks.kind.{k.value}")) for k in KindTest])
        self.kind.chosen.connect(lambda v: self._edit_match(kind=KindTest(v)))
        form.addRow(tr("settings.tracks.kind"), self.kind)
        languages = QVBoxLayout()
        languages.setSpacing(SIZES["space_xs"])
        self.languages = ProblemEditor(self._theme, tr("settings.tracks.languages_placeholder"))
        self.languages.field.edited.connect(lambda text: self._edit_match(languages=split_entries(text)))
        self.language_names = label("", "muted", wrap=True, size="sm")
        languages.addWidget(self.languages)
        languages.addWidget(self.language_names)
        form.addRow(tr("settings.tracks.languages"), languages)
        self.codecs = ProblemEditor(self._theme, tr("settings.tracks.codecs_placeholder"))
        self.codecs.field.edited.connect(lambda text: self._edit_match(codecs=split_entries(text)))
        form.addRow(tr("settings.tracks.codecs"), self.codecs)
        channels = QHBoxLayout()
        self.low, self.high = QSpinBox(), QSpinBox()
        for box, field in ((self.low, "min_channels"), (self.high, "max_channels")):
            box.setRange(0, 24)
            box.setSpecialValueText(tr("settings.tracks.any"))
            box.valueChanged.connect(lambda value, f=field: self._edit_match(**{f: value}))
        channels.addWidget(self.low)
        channels.addWidget(label(tr("settings.tracks.channels_to")))
        channels.addWidget(self.high)
        channels.addStretch()
        channel_box = QVBoxLayout()
        channel_box.addLayout(channels)
        self.channel_problem = label("", "danger", wrap=True, size="sm")
        channel_box.addWidget(self.channel_problem)
        form.addRow(tr("settings.tracks.channels"), channel_box)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SIZES["space_md"])
        grid.setVerticalSpacing(SIZES["space_xs"])
        self.flag_tests: dict[str, QComboBox] = {}
        for number, flag in enumerate(FLAG_TESTS):
            row, column = divmod(number, 3)
            box = QComboBox()
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(4)
            for test in FlagTest:
                box.addItem(tr(f"settings.tracks.test.{test.value}"), test.value)
            box.currentIndexChanged.connect(
                lambda _i, f=flag, b=box: self._edit_match(**{f: FlagTest(b.currentData())})
            )
            self.flag_tests[flag] = box
            grid.addWidget(label(tr(f"settings.tracks.flag.{flag}"), "muted", size="sm"), row * 2, column)
            grid.addWidget(box, row * 2 + 1, column)
        form.addRow(tr("settings.tracks.flags"), grid)
        name_row = QHBoxLayout()
        self.name = ProblemEditor(self._theme, tr("settings.tracks.name_placeholder"))
        self.name.field.edited.connect(lambda text: self._edit_match(name=text))
        self.regex = QCheckBox(tr("settings.tracks.regex"))
        self.regex.toggled.connect(lambda on: self._edit_match(name_is_regex=on))
        name_row.addWidget(self.name, 1)
        name_row.addWidget(self.regex, 0, Qt.AlignmentFlag.AlignTop)
        form.addRow(tr("settings.tracks.name"), name_row)
        form.addRow(heading(tr("settings.tracks.then")))
        self.verdict = Segmented([(v.value, tr(f"settings.tracks.verdict.{v.value}")) for v in Verdict])
        self.verdict.chosen.connect(lambda v: self._edit(verdict=Verdict(v)))
        form.addRow(tr("settings.tracks.verdict"), self.verdict)
        self.shapes: dict[str, QComboBox] = {}
        for flag in ("default", "forced"):
            box = QComboBox()
            for shape in FlagShape:
                box.addItem(tr(f"settings.tracks.shape.{shape.value}"), shape.value)
            box.currentIndexChanged.connect(lambda _i, f=flag, b=box: self._edit(**{f: FlagShape(b.currentData())}))
            self.shapes[flag] = box
            form.addRow(tr(f"settings.tracks.{flag}_flag"), box)
        self.editor = editor
        return editor

    # Inputs

    def set_item(self, item: MediaItem | None) -> None:
        self._item = item
        self._show_result()

    def select_rule(self, index: int) -> None:
        if 0 <= index < self.list.count():
            self.list.setCurrentRow(index)

    @property
    def options(self) -> TracksOptions:
        return self._session.options("tracks")

    def problems(self) -> list[RuleProblem]:
        return check_rules(self.options)

    def has_problem(self) -> bool:
        return bool(self.problems())

    # Showing

    def refresh(self) -> None:
        options = self.options
        self._loading = True
        self.use.setChecked(options.enabled)
        self.from_names.setChecked(options.flags_from_names)
        row = max(self.list.currentRow(), 0)
        problems = {p.rule_index for p in self.problems()}
        dot = dot_icon(self._theme.roles["danger"])
        self.list.clear()
        for index, rule in enumerate(options.rules):
            verdict = tr(f"settings.tracks.verdict.{rule.verdict.value}")
            title = rule.label or rule_summary(rule)
            item = QListWidgetItem(f"{index + 1}  {title}  ·  {verdict}\n{rule_summary(rule)}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setIcon(dot if index in problems else QIcon())
            self.list.addItem(item)
        self._loading = False
        if options.rules:
            self.list.setCurrentRow(min(row, len(options.rules) - 1))
        self._show_rule()
        self._show_result()

    def _rule(self) -> tuple[int, TrackRule] | None:
        row = self.list.currentRow()
        rules = self.options.rules
        return (row, rules[row]) if 0 <= row < len(rules) else None

    def _show_rule(self) -> None:
        current = self._rule()
        self.editor.setEnabled(current is not None)
        if current is None:
            self.rule_title.setText(tr("settings.tracks.no_rule"))
            return
        index, rule = current
        match = rule.match
        self._loading = True
        self.rule_title.setText(tr("settings.tracks.rule", number=index + 1))
        self.rule_on.setChecked(rule.enabled)
        if not self.label_field.hasFocus():
            self.label_field.setText(rule.label)
        self.kind.set_value(match.kind.value)
        for editor, entries in ((self.languages, match.languages), (self.codecs, match.codecs)):
            # Rewriting the text as typed would move the cursor while the user types `tur,eng`.
            if split_entries(editor.field.text()) != entries:
                editor.field.set_text(", ".join(entries))
        self.low.setValue(match.min_channels)
        self.high.setValue(match.max_channels)
        for flag, box in self.flag_tests.items():
            box.setCurrentIndex(box.findData(getattr(match, flag).value))
        self.name.field.set_text(match.name)
        self.regex.setChecked(match.name_is_regex)
        self.verdict.set_value(rule.verdict.value)
        for flag, box in self.shapes.items():
            box.setCurrentIndex(box.findData(getattr(rule, flag).value))
        self._loading = False

        mine = [p for p in self.problems() if p.rule_index == index]
        spans = entry_spans(self.languages.field.text())
        self.languages.set_problems(
            [
                rule_problem(p, spans[p.entry][0] if p.entry is not None and p.entry < len(spans) else 0)
                for p in mine
                if p.field is RuleField.LANGUAGES
            ]
        )
        self.name.set_problems([rule_problem(p) for p in mine if p.field is RuleField.NAME])
        channel = [rule_problem(p) for p in mine if p.field is RuleField.CHANNELS]
        self.channel_problem.setText(channel[0].message if channel else "")
        self.channel_problem.setVisible(bool(channel))
        names = []
        for tag in match.languages:
            if tag.casefold() == NO_LANGUAGE:
                names.append(tr("settings.tracks.no_language"))
            elif (language := Language.parse(tag)) is not None:
                names.append(language.name)
        help_text = tr("settings.tracks.languages_help")
        self.language_names.setText(f"{', '.join(names)}. {help_text}" if names else help_text)
        if match == TrackMatch():
            self.channel_problem.setText(tr("problem.fits_every_track"))
            self.channel_problem.setProperty("role", "muted")
            self.channel_problem.setVisible(True)
        else:
            self.channel_problem.setProperty("role", "danger")
        self.channel_problem.style().unpolish(self.channel_problem)
        self.channel_problem.style().polish(self.channel_problem)

    def _show_result(self) -> None:
        model = self.result_model
        model.clear()
        model.setHorizontalHeaderLabels([tr(f"settings.tracks.result.col.{c}") for c in _RESULT_COLUMNS])
        self.strip.hide()
        self.remux.setText("")
        if self._item is None:
            self.result_title.setText(tr("settings.tracks.result.title_none"))
            self.strip.setText(tr("settings.tracks.result.no_selection"))
            self.strip.setProperty("role", "preview_strip")
            self.strip.show()
            self.result.hide()
            return
        self.result.show()
        item = self._item
        self.result_title.setText(tr("settings.tracks.result.title", name=item_title(item)))
        options = self.options
        plan = plan_tracks(item, options)
        broken = [p for p in self.problems() if options.rules[p.rule_index].enabled]
        if broken and options.enabled:
            numbers = ", ".join(str(n + 1) for n in sorted({p.rule_index for p in broken}))
            self._strip(tr("settings.tracks.result.rule_problem", rules=numbers), "danger_strip")
        rows: list[tuple[Track, str, list[str], bool, str]] = []  # track, outcome, flags, struck, mark
        if isinstance(plan, PlanRefused):
            would = {d.track.id: d for p in plan.problems for d in p.dropped}
            kinds = ", ".join(tr(f"settings.tracks.refused.{p.kind.value}") for p in plan.problems)
            self._strip(tr("settings.tracks.result.refused", what=kinds), "notice_strip")
            for track in item.file.tracks:
                drop = would.get(track.id)
                outcome = dropped_text(drop, would=True) if drop else tr("common.none")
                rows.append((track, outcome, flag_names(track.flags), False, ""))
        else:
            kept = {k.track.id: k for k in plan.kept if k.external is None}
            dropped = {d.track.id: d for d in plan.dropped if d.external is None}
            for track in item.file.tracks:
                if (drop := dropped.get(track.id)) is not None:
                    rows.append((track, dropped_text(drop), [], True, ""))
                    continue
                planned = kept[track.id]
                changes = [
                    tr(f"settings.tracks.result.flag_{c.flag.value}_{'on' if c.value else 'off'}")
                    for c in planned.flag_changes
                ]
                outcome = " · ".join([tr("settings.tracks.result.kept"), *changes])
                rows.append((track, outcome, flag_names(planned.flags), False, ""))
            for planned in plan.kept:
                if planned.external is not None:
                    outcome = tr("settings.tracks.result.added", file=planned.external.path.name)
                    rows.append((planned.track, outcome, flag_names(planned.flags), False, "+"))
            if plan.needs_remux:
                self.remux.setText(tr("settings.tracks.result.needs_remux"))
            elif any(k.flag_changes for k in plan.kept):
                self.remux.setText(tr("settings.tracks.result.header_only"))
            else:
                self.remux.setText(tr("settings.tracks.result.no_change"))
        for track, outcome, flags, struck, mark in rows:
            number = mark or str(track.id)
            cells = [
                number,
                tr(f"settings.tracks.kind.{track.kind.value}"),
                language_code(track.language),
                track_summary(track) + (f" “{track.name}”" if track.name else ""),
                outcome,
                " · ".join(flags),
            ]
            items = [QStandardItem(text) for text in cells]
            for cell in items:
                cell.setEditable(False)
                if struck:
                    font = QFont(cell.font())
                    font.setStrikeOut(True)
                    cell.setFont(font)
                    cell.setForeground(self.palette().placeholderText())
            model.appendRow(items)
        header = self.result.header()
        header.setStretchLastSection(False)
        for column in range(len(_RESULT_COLUMNS)):
            mode = QHeaderView.ResizeMode.Stretch if column == 4 else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)
        self.result.fit()

    def _strip(self, text: str, role: str) -> None:
        self.strip.setText(text)
        self.strip.setProperty("role", role)
        self.strip.style().unpolish(self.strip)
        self.strip.style().polish(self.strip)
        self.strip.show()

    def _footer_problems(self) -> str:
        block = self._session.blocks().get("tracks")
        if not block:
            return ""
        numbers = ", ".join(str(n + 1) for n in sorted({p.rule_index for p in block.rules}))
        return tr("settings.tracks.footer_problems", rules=numbers)

    # Edits

    def _set_rules(self, rules: list[TrackRule]) -> None:
        self._session.update("tracks", rules=rules)

    def _edit(self, **changes: object) -> None:
        if self._loading or (current := self._rule()) is None:
            return
        index, rule = current
        rules = list(self.options.rules)
        rules[index] = replace(rule, **changes)  # type: ignore[arg-type]
        self._set_rules(rules)

    def _edit_match(self, **changes: object) -> None:
        if self._loading or (current := self._rule()) is None:
            return
        self._edit(match=replace(current[1].match, **changes))  # type: ignore[arg-type]

    def _list_edited(self) -> None:
        """The list was reordered by dragging, or a rule's check box was clicked."""
        if self._loading:
            return
        rules = self.options.rules
        order = [self.list.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.list.count())]
        fresh = [
            replace(rules[index], enabled=self.list.item(row).checkState() == Qt.CheckState.Checked)
            for row, index in enumerate(order)
        ]
        if fresh != rules:
            moved = self.list.currentRow()
            self._set_rules(fresh)
            self.list.setCurrentRow(moved)

    def _add(self) -> None:
        rules = [*self.options.rules, TrackRule(label=tr("settings.tracks.new_rule"))]
        self._set_rules(rules)
        self.list.setCurrentRow(len(rules) - 1)

    def _move(self, step: int) -> None:
        if (current := self._rule()) is None:
            return
        index, rule = current
        target = index + step
        rules = list(self.options.rules)
        if not 0 <= target < len(rules):
            return
        rules[index], rules[target] = rules[target], rule
        self._set_rules(rules)
        self.list.setCurrentRow(target)

    def _duplicate(self) -> None:
        if (current := self._rule()) is None:
            return
        index, rule = current
        rules = list(self.options.rules)
        rules.insert(index + 1, rule)
        self._set_rules(rules)
        self.list.setCurrentRow(index + 1)

    def _delete(self) -> None:
        if (current := self._rule()) is None:
            return
        index, _ = current
        self._set_rules([r for n, r in enumerate(self.options.rules) if n != index])
