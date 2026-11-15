"""Planned changes on the sheet: one line per switched-on stage, saying in words what Apply would do to the file,
or why it would not, with the way to fix it."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from showrunner.app.jobs.blocked import StageBlock
from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.app.jobs.stages import PlanState, StagePlan
from showrunner.core.track import Track
from showrunner.stages.metadata import MetadataPlan, MetadataRefused
from showrunner.stages.tracks import DroppedTrack, PlanRefused, TrackPlan
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.library.marks import MarkDot
from showrunner.ui.settings.page import clear_layout, heading, label, link_button
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

# What each mark of a line says, as a color role; None draws no mark.
_ROLES = {"planned": "control", "refused": "accent_ink", "blocked": "danger", "none": None}


@dataclass(frozen=True, slots=True)
class Line:
    stage: str
    text: str
    state: str  # planned, refused, blocked or none
    actions: tuple[tuple[str, str, int], ...] = field(default=())  # caption, page, rule index or -1


def _sentence(parts: list[str], joiner: str) -> str:
    text = tr("plan.sentence", text=joiner.join(parts))
    return text[:1].upper() + text[1:]


def track_name(track: Track) -> str:
    return tr("plan.track", kind=tr(f"plan.kind.{track.kind.value}"), id=track.id)


def _rule(drop: DroppedTrack) -> str:
    return tr("settings.tracks.rule_named", number=drop.rule_index + 1, label=drop.rule.label or "")


def _drops(drops: tuple[DroppedTrack, ...]) -> str:
    """`audio 3 (rule 1 Drop commentary) and subtitles 4 and 5 (rule 6 Drop other subtitles)`."""
    by_rule: dict[int, list[DroppedTrack]] = {}
    for drop in drops:
        by_rule.setdefault(drop.rule_index, []).append(drop)
    parts = []
    for group in by_rule.values():
        names = tr("common.list_separator").join(
            d.external.path.name if d.external is not None else track_name(d.track) for d in group
        )
        parts.append(tr("plan.by_rule", tracks=names, rule=_rule(group[0]).strip()))
    return tr("plan.and").join(parts)


def tracks_line(plan: StagePlan, file: FilePreview, blocks: dict[str, StageBlock]) -> Line:
    if plan.state is PlanState.BLOCKED:
        rules = sorted({p.rule_index for p in blocks["tracks"].rules}) if "tracks" in blocks else [0]
        numbers = ", ".join(str(n + 1) for n in rules)
        caption = tr("plan.edit_rule", number=rules[0] + 1)
        return Line("tracks", tr("plan.not_planned_rules", rules=numbers), "blocked", ((caption, "tracks", rules[0]),))
    result = plan.plan
    if isinstance(result, PlanRefused):
        what = tr("plan.and").join(tr(f"settings.tracks.refused.{p.kind.value}") for p in result.problems)
        reasons = "; ".join(_drops(p.dropped) for p in result.problems)
        # The broadest rule, usually the catch-all near the end, is the one to edit.
        last = max(d.rule_index for p in result.problems for d in p.dropped)
        actions = ((tr("plan.edit_rule", number=last + 1), "tracks", last), (tr("plan.track_rules"), "tracks", -1))
        return Line("tracks", tr("plan.tracks_refused", what=what, reasons=reasons), "refused", actions)
    if not isinstance(result, TrackPlan) or plan.state is PlanState.UNCHANGED:
        return Line("tracks", tr("plan.nothing"), "none")
    parts = []
    if result.dropped:
        parts.append(tr("plan.drops", what=_drops(result.dropped)))
    if added := [k.external.path.name for k in result.kept if k.external is not None]:
        parts.append(tr("plan.adds", files=tr("common.list_separator").join(added)))
    flags = [
        tr(f"plan.flag_{c.flag.value}_{'on' if c.value else 'off'}", track=track_name(k.track))
        for k in result.kept
        if k.external is None
        for c in k.flag_changes
    ]
    if flags:
        parts.append(tr("common.list_separator").join(flags))
    text = _sentence(parts, "; ")
    if file.outcome is FileOutcome.NEEDS_REMUX:
        return Line("tracks", f"{text} {tr('plan.needs_remux_nothing')}", "refused")
    if file.outcome is FileOutcome.UNWRITTEN:
        return Line("tracks", f"{text} {tr('plan.unwritten')}", "refused")
    return Line("tracks", text + (f" {tr('plan.needs_remux')}" if result.needs_remux else ""), "planned")


def metadata_line(plan: StagePlan, file: FilePreview, blocks: dict[str, StageBlock]) -> Line:
    if plan.state is PlanState.BLOCKED:
        count = blocks["metadata"].count if "metadata" in blocks else 1
        actions = ((tr("plan.open_naming"), "naming", -1),)
        return Line("metadata", tr_plural("plan.not_planned_naming", count), "blocked", actions)
    result = plan.plan
    if isinstance(result, MetadataRefused):
        reasons = "; ".join(tr(f"plan.metadata.{p.kind.value}", detail=p.detail) for p in result.problems)
        return Line("metadata", tr("plan.metadata_refused", reasons=reasons), "refused")
    if not isinstance(result, MetadataPlan) or not result.changes:
        return Line("metadata", tr("plan.nothing"), "none")
    changes = result.changes
    parts = [tr("plan.sets_title", title=c.new) for c in changes if c.prop is Property.TITLE]
    for prop, key in ((Property.NAME, "plan.names"), (Property.LANGUAGE, "plan.languages")):
        if count := sum(c.prop is prop for c in changes):
            parts.append(tr_plural(key, count))
    if flags := sum(c.prop not in (Property.TITLE, Property.NAME, Property.LANGUAGE) for c in changes):
        parts.append(tr_plural("plan.flags_written", flags))
    text = _sentence(parts, tr("plan.and"))
    if result.needs_remux:
        return Line("metadata", tr("plan.metadata_waits", text=text), "refused")
    return Line("metadata", text, "planned")


def lines(file: FilePreview, blocks: dict[str, StageBlock]) -> list[Line]:
    if file.outcome is FileOutcome.MISSING:
        return [Line("", tr("plan.missing", error=file.error), "blocked")]
    builders = {"tracks": tracks_line, "metadata": metadata_line}
    return [builders[p.stage](p, file, blocks) for p in file.plans if p.stage in builders]


def state_of(file: FilePreview) -> tuple[str, str | None]:
    """The words and the dot role for the title row of the sheet."""
    if file.outcome is FileOutcome.REFUSED:
        return tr("plan.state.refused"), "accent_ink"
    if file.outcome is FileOutcome.NEEDS_REMUX:
        return tr("plan.state.needs_remux"), "accent_ink"
    if file.outcome is FileOutcome.UNWRITTEN:
        return tr("plan.state.unwritten"), "accent_ink"
    if file.outcome is FileOutcome.MISSING:
        return tr("plan.state.missing"), "danger"
    if file.outcome is FileOutcome.CHANGES:
        return tr("plan.changes_planned"), "control"
    return tr("plan.state.unchanged"), None


class PlannedChanges(QWidget):
    """`open_page` asks for a Settings page; `open_rule` for a rule by index;
    `leave_out` toggles whether Apply skips this file."""

    open_page = Signal(str)
    open_rule = Signal(int)
    leave_out = Signal(bool)

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES["space_sm"])
        top = QHBoxLayout()
        top.addWidget(heading(tr("plan.title")))
        top.addStretch()
        self.leave = link_button(tr("plan.leave_out"))
        self.leave.setCheckable(True)
        self.leave.toggled.connect(self._on_leave)
        top.addWidget(self.leave)
        layout.addLayout(top)
        self.note = label("", "notice", wrap=True, size="sm")
        layout.addWidget(self.note)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(SIZES["space_lg"])
        self.grid.setVerticalSpacing(SIZES["space_md"])
        self.grid.setColumnStretch(2, 1)
        layout.addLayout(self.grid)
        self.texts: list[str] = []

    def show_file(self, file: FilePreview, blocks: dict[str, StageBlock], *, current: bool, left_out: bool) -> None:
        clear_layout(self.grid)
        self.note.setText("" if current else tr("plan.out_of_date"))
        self.note.setVisible(not current)
        self.leave.blockSignals(True)
        self.leave.setChecked(left_out)
        self.leave.setText(tr("plan.include" if left_out else "plan.leave_out"))
        self.leave.blockSignals(False)
        self.texts = []
        for row, line in enumerate(lines(file, blocks)):
            dot = MarkDot(self._theme)
            dot.set_role(_ROLES[line.state])
            self.grid.addWidget(dot, row, 0, Qt.AlignmentFlag.AlignTop)
            name = QLabel(tr(f"stage.{line.stage}") if line.stage else "")
            name.setProperty("heading", True)
            self.grid.addWidget(name, row, 1, Qt.AlignmentFlag.AlignTop)
            role = {"refused": "notice", "blocked": "danger"}.get(line.state, "")
            self.grid.addWidget(label(line.text, role, wrap=True), row, 2)
            self.texts.append(line.text)
            actions = QHBoxLayout()
            for caption, page, rule in line.actions:
                if rule >= 0:
                    button = link_button(caption, lambda r=rule: self.open_rule.emit(r))
                else:
                    button = link_button(caption, lambda p=page: self.open_page.emit(p))
                actions.addWidget(button)
            self.grid.addLayout(actions, row, 3, Qt.AlignmentFlag.AlignTop)

    def _on_leave(self, checked: bool) -> None:
        self.leave.setText(tr("plan.include" if checked else "plan.leave_out"))
        self.leave_out.emit(checked)
