"""The Subtitles place: the open place's subtitle settings as rows, each with where its value comes from, and the
batch's files with the finished subtitles each gets. Every edit ends in the open place's own subtitle options.

A row's menu takes the place back to what it receives ("Follow the show again") or makes "as it is" its own value. The
wanted languages and the rule sets are marked item by item, since a nearer place adds or cancels single items of
them.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.app.batches.batch import BatchKey
from showrunner.core.language import Language
from showrunner.stages.subtitles import (
    Approval,
    Lines,
    RuleSetUse,
    SubtitlePlan,
    SubtitlesOptions,
    SyncEngine,
    Wanted,
)
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.quick.languages import LanguagePicker
from showrunner.ui.quick.review import missing_phases
from showrunner.ui.quick.tracks import code, item_number
from showrunner.ui.quick.workspace import Workspace

STAGE = "subtitles"
# The rows in the order of the work, each with the field it shows.
ROWS = (
    ("wanted", "languages"),
    ("reference", "reference"),
    ("cleanup", "cleanup"),
    ("sync", "sync"),
    ("lines", "lines"),
    ("model", "model"),
    ("approval", "approval"),
)
# The rows chosen from a few values, drawn as segments.
CHOICES: dict[str, type[StrEnum]] = {"sync": SyncEngine, "lines": Lines, "approval": Approval}
# The value that cancels one received item of a per-item field.
_NOT_HERE: dict[str, StrEnum] = {"languages": Wanted.NOT_HERE, "cleanup": RuleSetUse.PAUSED}
_PICKER_TARGET = "wanted"
# The Jobs phases of the work each row asks for, so a row says when its work is not available and is left out.
_ROW_WORK: dict[str, tuple[str, ...]] = {
    "wanted": ("translate",),
    "reference": ("reference", "ocr"),
    "cleanup": ("clean",),
    "sync": ("sync",),
    "lines": ("resplit",),
    "approval": ("approval",),
}


class SubtitleSettings(QObject):
    subtitles_changed = Signal()

    def __init__(self, workspace: Workspace, picker: LanguagePicker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._picker = picker
        self._built: dict[str, Any] | None = None
        self._stale = False  # the settings or the plan changed while the place was hidden
        workspace.rebuilt.connect(self.refresh)
        workspace.batch_changed.connect(self.refresh)
        workspace.place_shown.connect(self._on_place_shown)
        picker.applied.connect(self._on_language_picked)

    def _on_place_shown(self) -> None:
        if self._workspace.place == "subtitles" and self._stale:
            self.refresh()

    def refresh(self) -> None:
        """Build what the place shows, and tell QML only when it changed. While the place is hidden nothing is built:
        it is built when read, and QML hears of it on switching to the place."""
        if self._workspace.place != "subtitles":
            self._built, self._stale = None, True
            return
        self._stale = False
        built = self._build() if self._workspace.key is not None else {}
        if built != self._built:
            self._built = built
            self.subtitles_changed.emit()

    @property
    def subtitles(self) -> dict[str, Any]:
        """The box's title and rows and the file list, or empty while no place is open."""
        if self._built is None:
            self._built = self._build() if self._workspace.key is not None else {}
        return self._built

    # Edits

    def _options(self) -> SubtitlesOptions:
        assert self._workspace.key is not None
        return self._workspace.batches.profile(self._workspace.key).for_stage(STAGE)

    def _received(self) -> SubtitlesOptions | None:
        assert self._workspace.key is not None
        received = self._workspace.batches.received(self._workspace.key)
        return received.for_stage(STAGE) if received is not None else None

    def _set(self, **changes: Any) -> None:
        if self._workspace.key is not None:
            self._workspace.set_options(STAGE, replace(self._options(), **changes))

    def set_choice(self, row: str, value: str) -> None:
        """A segment picked on the Sync, Lines or Approval row."""
        if row in CHOICES:
            self._set(**{row: CHOICES[row](value)})

    def follow(self, row: str) -> None:
        """The row's own value removed, so the place follows its parent there again."""
        received = self._received() if self._workspace.key is not None else None
        if received is not None:
            name = dict(ROWS)[row]
            self._set(**{name: getattr(received, name)})

    def as_it_is(self, row: str) -> None:
        """ "As it is" as the row's own value: the empty value, or every received item cancelled."""
        if self._workspace.key is None:
            return
        name = dict(ROWS)[row]
        received = self._received()
        if name in _NOT_HERE:
            given = getattr(received, name) if received is not None else {}
            self._set(**{name: dict.fromkeys(given, _NOT_HERE[name])})
        else:
            self._set(**{name: getattr(SubtitlesOptions(), name)})

    def toggle_item(self, row: str, item: str) -> None:
        """The remove button of a wanted language or the pause of a rule set: an own item goes, a received one is
        cancelled here, and a cancelled one is taken back."""
        if self._workspace.key is None:
            return
        name = dict(ROWS)[row]
        values = dict(getattr(self._options(), name))
        received = self._received()
        given = getattr(received, name).get(item) if received is not None else None
        on = Wanted.WANTED if name == "languages" else RuleSetUse.USED
        if values.get(item) is _NOT_HERE[name]:
            values[item] = on
        elif given is on:
            values[item] = _NOT_HERE[name]
        else:
            values.pop(item, None)
        self._set(**{name: values})

    def pick_language(self) -> None:
        """Open the language picker for a wanted language to add."""
        if self._workspace.key is not None and not self._workspace.locked:
            self._picker.begin(_PICKER_TARGET, tr("subtitles.row.wanted"), "")

    def _on_language_picked(self, target: str, tag: str) -> None:
        if target == _PICKER_TARGET and tag and self._workspace.key is not None:
            self._set(languages={**self._options().languages, tag: Wanted.WANTED})

    # What the place shows

    def _build(self) -> dict[str, Any]:
        key = self._workspace.key
        assert key is not None
        options = self._options()
        missing = {
            phase
            for file in self._workspace.current_files()
            if (stage := file.plan_for(STAGE)) is not None and isinstance(stage.plan, SubtitlePlan)
            for finished in stage.plan.left_out
            for phase in missing_phases(finished)
        }
        rows = [self._row(key, row, name, options) for row, name in ROWS]
        for shown in rows:
            lacking = [phase for phase in _ROW_WORK.get(shown["key"], ()) if phase in missing]
            shown["note"] = unavailable(lacking[0]) if lacking else ""
        return {
            "title": tr(f"subtitles.box.{key.kind.value}"),
            "rows": rows,
            "follow": tr("subtitles.menu.follow", parent=tr(f"discard.parent.{key.parent.kind.value}"))
            if key.parent is not None
            else "",
            "files": self._files(),
        }

    def _row(self, key: BatchKey, row: str, name: str, options: SubtitlesOptions) -> dict[str, Any]:
        batches = self._workspace.batches
        origin = batches.field_origin(key, STAGE, name)
        shown: dict[str, Any] = {
            "key": row,
            "label": tr(f"subtitles.row.{row}"),
            # Only a nearer place has a value of its own to take back.
            "own": key.parent is not None and name in batches.own(key).get(STAGE, {}),
            "received": origin is not None and origin != key,
        }
        value = getattr(options, name)
        if row in CHOICES:
            shown["choices"] = [
                {"key": v.value, "label": tr(f"subtitles.{row}.{v.name.lower()}")} for v in CHOICES[row]
            ]
            shown["value"] = value.value
        elif name in _NOT_HERE:
            shown["items"] = [self._item(key, name, item, state) for item, state in value.items()]
            shown["empty"] = tr("tracks.rule.as_it_is")
        elif row == "reference":
            shown["text"] = tr(f"subtitles.reference.{value.kind.name.lower()}")
        else:
            shown["text"] = value or tr("subtitles.model.settings")
        return shown

    def _item(self, key: BatchKey, name: str, item: str, state: StrEnum) -> dict[str, Any]:
        """One wanted language or rule set with its mark: from the place that set it, or over the one it cancels."""
        batches = self._workspace.batches
        origin = batches.item_origin(key, STAGE, name, item)
        above = batches.item_origin(key.parent, STAGE, name, item) if key.parent is not None else None
        if origin is not None and origin != key:
            mark = {"from": tr(f"place.from.{origin.kind.value}"), "over": ""}
        else:
            mark = {"from": "", "over": tr(f"place.over.{above.kind.value}") if above is not None else ""}
        language = Language.parse(item) if name == "languages" else None
        return {
            "key": item,
            "label": code(language) if language is not None else item,
            "name": language.name if language is not None else item,
            "off": state is _NOT_HERE[name],
            "own": origin == key,
            "mark": mark,
        }

    def _files(self) -> list[dict[str, Any]]:
        """Each file of the batch with its subtitles now and the finished subtitles its plan makes, step by step."""
        planned = {f.item.file.path: f for f in self._workspace.current_files()}
        rows = []
        for item in self._workspace.items:
            file = planned.get(item.file.path)
            stage = file.plan_for(STAGE) if file is not None else None
            work = stage.plan if stage is not None and isinstance(stage.plan, SubtitlePlan) else None
            now = [code(t.language) for t in item.file.subtitle_tracks] + [
                f"+{code(s.language)}" for s in item.subtitles
            ]
            plan = []
            for finished in (*work.finished, *work.cannot, *work.left_out) if work is not None else ():
                steps = [tr(f"subtitles.step.{step.kind.value}") for step in finished.steps]
                if finished.waits:
                    steps.append(tr("subtitles.step.approve"))
                reasons = [tr(f"subtitles.cannot.{reason.value}") for reason in finished.cannot]
                reasons += [unavailable(phase) for phase in missing_phases(finished)[:1]]
                plan.append(
                    {
                        "code": code(finished.language),
                        "steps": tr("subtitles.list.steps_separator").join(steps),
                        "cannot": tr("common.list_separator").join(reasons),
                    }
                )
            rows.append(
                {
                    "path": str(item.file.path),
                    "number": item_number(item),
                    "file": item.file.path.name,
                    "now": now,
                    "plan": plan,
                }
            )
        return rows


def unavailable(phase: str) -> str:
    """ "Sync is not available in this version yet." """
    return tr("subtitles.unavailable", step=tr(f"jobs.phase.{phase}"))
