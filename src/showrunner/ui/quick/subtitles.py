"""The Subtitles place: the open place's subtitle settings as rows, each with where its value comes from, and the
batch's files with the finished subtitles each gets. Every edit ends in the open place's own subtitle options.

A row's menu takes the place back to what it receives ("Follow the show again") or makes "as it is" its own value. The
wanted languages and the rule sets are marked item by item, since a nearer place adds or cancels single items of
them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from showrunner.app.ai import AI
from showrunner.app.batches.batch import BatchKey
from showrunner.app.batches.choices import TrackGroups, TrackSignature
from showrunner.app.jobs.hashing import stamp
from showrunner.app.library.loader import BackgroundJob
from showrunner.app.rules import RULES, RuleStore
from showrunner.app.rules.effect import file_effect
from showrunner.app.settings.app_settings import load_settings
from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.track import Track
from showrunner.stages.subtitles import (
    Approval,
    Lines,
    Output,
    Reference,
    ReferenceKind,
    RuleSetUse,
    Source,
    StepKind,
    SubtitlePlan,
    SubtitlesOptions,
    SyncEngine,
    Wanted,
    choose_reference,
)
from showrunner.tools.cleanit import RuleBook, RuleSet
from showrunner.tools.sync import ENGINES, IN_SYNC_BELOW, UNSURE_BELOW, Setting, SettingKind
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.languages import LanguagePicker
from showrunner.ui.quick.review import (
    NEEDS,
    ai_model,
    backend_name,
    kept_sync,
    left_as_it_was,
    missing_phases,
    reference_text,
    sync_found,
    track_text,
)
from showrunner.ui.quick.tracks import code, item_number
from showrunner.ui.quick.workspace import Workspace

STAGE = "subtitles"
_EFFECTS_KEPT = 4000  # counted files kept; a season is a few hundred
_FALLBACKS_NAMED = 2  # files without the chosen reference named one by one; more are counted
# The rows in the order of the work, each with the field it shows.
ROWS = (
    ("wanted", "languages"),
    ("reference", "reference"),
    ("cleanup", "cleanup"),
    ("sync", "sync"),
    ("lines", "lines"),
    ("model", "model"),
    ("approval", "approval"),
    ("output", "output"),
)
# The rows chosen from a few values, drawn as segments.
CHOICES: dict[str, type[StrEnum]] = {"sync": SyncEngine, "lines": Lines, "approval": Approval, "output": Output}
# The value that cancels one received item of a per-item field.
_NOT_HERE: dict[str, StrEnum] = {"languages": Wanted.NOT_HERE, "cleanup": RuleSetUse.PAUSED}
_PICKER_TARGET = "wanted"
# The Reference row's menu entries that are no group.
_AUTOMATIC, _AUDIO = "automatic", "audio"
# The Jobs phases of the work each row asks for, so a row says when its work is not available and is left out.
_ROW_WORK: dict[str, tuple[str, ...]] = {
    "wanted": ("translate",),
    "reference": ("reference", "ocr"),
    "cleanup": ("clean", "read"),
    "sync": ("sync", "audio"),
    "lines": ("resplit",),
    "model": ("ai", "model", "no_model"),
    "approval": ("approval",),
}


def set_label(name: str) -> str:
    """The name a rule set is shown by: cleanit's own sets have a name of their own, a set of the user's is its name."""
    key = f"cleanup.set.{name}"
    shown = tr(key)
    return shown if shown != key else name


def set_languages(rule_set: RuleSet) -> str:
    """The languages a rule set works on, or that it works on every one."""
    return ", ".join(rule_set.languages) if rule_set.languages else tr("cleanup.any_language")


class SubtitleSettings(QObject):
    subtitles_changed = Signal()
    editor_asked = Signal(str)  # the rule editor is wanted, on the set of this name or on none

    def __init__(
        self,
        workspace: Workspace,
        picker: LanguagePicker,
        parent: QObject | None = None,
        *,
        rules: RuleStore = RULES,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._picker = picker
        self._rules = rules
        # What cleaning does to each paired file (lines dropped, lines changed), by the file's stamp and the rules that
        # clean it; read in the background, so a season of files never holds the window.
        self._effects: dict[tuple[Any, ...], tuple[int, int] | None] = {}
        self._counting = False
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
            # The engine's settings are the Sync row's too, so following the parent there takes them back as well.
            extra = {"sync_settings": received.sync_settings} if row == "sync" else {}
            self._set(**{name: getattr(received, name)}, **extra)

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

    def set_sync_setting(self, key: str, text: str) -> None:
        """A field of the Sync row's engine settings edited, `key` being `<engine>.<setting>`. A number that is none, or
        below zero, is not taken, and a decimal comma is read as a point. An emptied field gives the place back what it
        receives there, or the engine's own default where it receives nothing."""
        if self._workspace.key is None or self._workspace.locked:
            return
        text = text.strip()
        kind = self._declared(key)
        if kind is None:
            return
        if kind is SettingKind.NUMBER:
            text = text.replace(",", ".")  # a decimal comma, as many systems type it
            if text and not _is_number(text):
                return
        values = dict(self._options().sync_settings)
        received = self._received()
        given = received.sync_settings.get(key) if received is not None else None
        if text:
            values[key] = text
        elif given:
            values[key] = given
        else:
            values.pop(key, None)
        self._set(sync_settings=values)

    @staticmethod
    def _declared(key: str) -> SettingKind | None:
        engine, _, name = key.partition(".")
        found = ENGINES.get(engine)
        if found is None:
            return None
        if name in (IN_SYNC_BELOW, UNSURE_BELOW):
            return SettingKind.NUMBER
        return next((s.kind for s in found.settings if s.key == name), None)

    def pick_reference(self, key: str) -> None:
        """A choice of the Reference row's menu: Automatic, the audio, or one group of the batch's subtitle tracks."""
        if self._workspace.key is None:
            return
        groups = self._groups()
        if key == _AUTOMATIC:
            self._set(reference=Reference())
        elif key == _AUDIO:
            self._set(reference=Reference(ReferenceKind.AUDIO))
        elif key.isdigit() and int(key) < len(groups):
            self._set(reference=Reference(ReferenceKind.TRACK, groups[int(key)][0].match()))

    def pick_model(self, name: str) -> None:
        """A choice of the Translate with row's menu: an installed model, or empty for the one chosen in Settings."""
        if self._workspace.key is not None:
            self._set(model=name)

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
        # Each phase some file misses, with the model the first such subtitle asks for.
        missing: dict[str, str] = {}
        for file in self._workspace.current_files():
            if (stage := file.plan_for(STAGE)) is not None and isinstance(stage.plan, SubtitlePlan):
                for finished in stage.plan.left_out:
                    for phase in missing_phases(finished):
                        missing.setdefault(phase, ai_model(finished))
        rows = [self._row(key, row, name, options) for row, name in ROWS]
        for shown in rows:
            lacking = [phase for phase in _ROW_WORK.get(shown["key"], ()) if phase in missing]
            shown["note"] = unavailable(lacking[0], missing[lacking[0]]) if lacking else ""
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
            if row == "sync":
                shown["settings"] = self._sync_settings(key, options)
        elif name in _NOT_HERE:
            shown["items"] = [self._item(key, name, item, state) for item, state in value.items()]
            shown["empty"] = tr("tracks.rule.as_it_is")
            if name == "cleanup":
                shown["add"] = [
                    {
                        "key": rule_set.name,
                        "text": f"{set_label(rule_set.name)} · {set_languages(rule_set)}",
                        "enabled": True,
                    }
                    for rule_set in self._rules.book().chosen()
                    if rule_set.name not in value
                ]
                shown["count"] = self._cleanup_count()
        elif row == "reference":
            shown.update(self._reference(value, options))
        else:
            shown.update(self._model(value))
        return shown

    @staticmethod
    def _model(value: str) -> dict[str, Any]:
        """The Translate with row: the model in words, the Settings one where the place chooses none, and the menu of
        the installed models. A model is said to be missing only while the server answers and lacks it."""
        status = AI.status()
        installed = status.models if status is not None and status.running else ()
        default = load_settings().value.ai_model
        if value:
            missing = status is not None and status.running and value not in installed
            text = tr("subtitles.model.not_installed", model=value) if missing else value
        elif default:
            text = tr("subtitles.model.settings", model=default, backend=backend_name())
        else:
            text = tr("subtitles.model.unset")
        pick = [{"key": "", "text": tr("subtitles.model.follow_settings"), "enabled": True}]
        pick += [{"key": name, "text": name, "enabled": True} for name in installed]
        return {"text": text, "pick": pick}

    def _sync_settings(self, key: BatchKey, options: SubtitlesOptions) -> list[dict[str, Any]]:
        """The fields under the Sync row: the two thresholds, then the chosen engine's own settings, each with its own
        value, what it receives (or the engine's default) as the placeholder, and where it comes from."""
        engine = ENGINES.get(options.sync.value)
        if engine is None:
            return []
        batches = self._workspace.batches
        common = [Setting(name, SettingKind.NUMBER, engine.defaults[name]) for name in (IN_SYNC_BELOW, UNSURE_BELOW)]
        fields = []
        for setting in (*common, *engine.settings):
            full = f"{engine.name}.{setting.key}"
            origin = batches.item_origin(key, STAGE, "sync_settings", full)
            above = batches.item_origin(key.parent, STAGE, "sync_settings", full) if key.parent is not None else None
            if origin is not None and origin != key:
                mark = {"from": tr(f"place.from.{origin.kind.value}"), "over": ""}
            else:
                mark = {"from": "", "over": tr(f"place.over.{above.kind.value}") if above is not None else ""}
            given = options.sync_settings.get(full, "")
            own = origin == key
            label = f"subtitles.sync.{setting.key if setting in common else f'{engine.name}.{setting.key}'}"
            shown: dict[str, Any] = {
                "key": full,
                "label": tr(label),
                "number": setting.kind is SettingKind.NUMBER,
                "value": given if own else "",
                "placeholder": given or setting.default,
                "own": own,
                "mark": mark,
            }
            if setting.kind is SettingKind.CHOICE:
                shown["choices"] = [
                    {"key": choice, "label": tr(f"{label}.{choice or 'default'}")} for choice in ("", *setting.choices)
                ]
                shown["current"] = given
            fields.append(shown)
        return fields

    def _flags_from_names(self) -> bool:
        """Whether the flags a track's name implies count, as the place's Tracks choices say."""
        assert self._workspace.key is not None
        return self._workspace.batches.profile(self._workspace.key).for_stage("tracks").flags_from_names

    def _groups(self) -> list[tuple[TrackSignature, Track, int]]:
        """The groups of subtitle tracks the batch's videos hold, in the order first seen: the signature the Tracks
        tab tells them apart by, a track of it, and how many files have one."""
        items = self._workspace.items
        grouping = TrackGroups.of(items, self._flags_from_names())
        first: dict[TrackSignature, Track] = {}
        files: Counter[TrackSignature] = Counter()
        for item in items:
            seen = {grouping.signature(track): track for track in item.file.subtitle_tracks}
            files.update(seen.keys())
            for signature, track in seen.items():
                first.setdefault(signature, track)
        return [(signature, track, files[signature]) for signature, track in first.items()]

    def _reference(self, value: Reference, options: SubtitlesOptions) -> dict[str, Any]:
        """The Reference row: its value in words, the menu of groups to pick from, what each file ends up working
        against, and the files that lack the chosen group."""
        groups = self._groups()
        chosen = next(
            (
                track
                for signature, track, _ in groups
                if value.kind is ReferenceKind.TRACK and signature.match() == value.track
            ),
            None,
        )
        if value.kind is ReferenceKind.TRACK:
            text = track_text(chosen) if chosen is not None else tr("subtitles.reference.track")
        else:
            text = tr(f"subtitles.reference.{value.kind.name.lower()}")
        pick = [{"key": _AUTOMATIC, "text": tr("subtitles.reference.automatic"), "enabled": True}]
        pick += [
            {
                "key": str(index),
                "text": tr(
                    "subtitles.reference.group", track=track_text(track), files=tr_plural("cleanup.files", count)
                ),
                "enabled": True,
            }
            for index, (_, track, count) in enumerate(groups)
        ]
        pick.append({"key": _AUDIO, "text": tr("subtitles.reference.audio"), "enabled": True})
        used: dict[str, list[MediaItem]] = {}
        lacking: list[MediaItem] = []
        flags = self._flags_from_names()
        for item in self._workspace.items:
            reference = choose_reference(item, options, flags_from_names=flags)
            used.setdefault(reference_text(reference), []).append(item)
            if reference.fallback:
                lacking.append(item)
        found = [
            tr("subtitles.reference.found", track=track, files=_files_text(files)) for track, files in used.items()
        ]
        return {
            "text": text,
            "pick": pick,
            "found": f" {tr('status.separator')} ".join(found),
            "fallbacks": self._fallbacks(lacking, chosen, options, flags),
        }

    @staticmethod
    def _fallbacks(lacking: list[MediaItem], chosen: Track | None, options: SubtitlesOptions, flags: bool) -> str:
        """The files the chosen group is missing in, each with the track Automatic used instead."""
        if not lacking:
            return ""
        wanted = track_text(chosen) if chosen is not None else tr("subtitles.reference.track")
        if len(lacking) > _FALLBACKS_NAMED:
            return tr_plural("subtitles.reference.fallback_many", len(lacking), track=wanted)
        return f" {tr('status.separator')} ".join(
            tr(
                "subtitles.reference.fallback",
                file=_file_label(item),
                track=wanted,
                other=reference_text(choose_reference(item, options, flags_from_names=flags)),
            )
            for item in lacking
        )

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
        shown: dict[str, Any] = {
            "key": item,
            "label": code(language) if language is not None else item,
            "name": language.name if language is not None else item,
            "off": state is _NOT_HERE[name],
            "own": origin == key,
            "mark": mark,
        }
        if name == "cleanup":
            rule_set = self._rules.book().sets.get(item)
            shown["name"] = set_label(item)
            shown["languages"] = set_languages(rule_set) if rule_set is not None else ""
            # A set that was deleted, or whose file is broken, cleans nothing until it is back.
            shown["missing"] = rule_set is None
        return shown

    def _cleanup_count(self) -> str:
        """What the chosen sets do to the paired files the plan cleans: lines dropped and changed, counted from the
        files as they are now. Empty until every file is counted, and for a plan without a cleaned file."""
        wanted: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        translated = False
        for file in self._workspace.current_files():
            stage = file.plan_for(STAGE)
            if stage is None or not isinstance(stage.plan, SubtitlePlan):
                continue
            for finished in stage.plan.finished:
                clean = next((step for step in finished.steps if step.kind is StepKind.CLEAN), None)
                if clean is None:
                    continue
                if finished.source is not Source.PAIRED or finished.paired is None:
                    translated = translated or finished.source is Source.TRANSLATION
                    continue
                path = finished.paired.path
                try:
                    key = (path, stamp(path), clean.sets, clean.rules, finished.language)
                except OSError:
                    continue
                wanted[key] = (path, finished.language, clean.sets)
        missing = {key: given for key, given in wanted.items() if key not in self._effects}
        if missing:
            self._count(missing)
            return ""
        counted = [found for key in wanted if (found := self._effects[key]) is not None]
        parts = []
        if counted:
            dropped, changed = (sum(c[n] for c in counted) for n in (0, 1))
            parts.append(
                tr(
                    "cleanup.count",
                    dropped=tr_plural("cleanup.lines", dropped),
                    changed=tr_plural("cleanup.lines", changed),
                    files=tr_plural("cleanup.files", len(counted)),
                )
            )
        if translated:
            parts.append(tr("cleanup.after_translation"))
        return tr("common.list_separator").join(parts)

    def _count(self, missing: dict[tuple[Any, ...], tuple[Any, ...]]) -> None:
        if self._counting:
            return
        self._counting = True
        book: RuleBook = self._rules.book()

        def work() -> dict[tuple[Any, ...], tuple[int, int] | None]:
            found: dict[tuple[Any, ...], tuple[int, int] | None] = {}
            for key, (path, language, names) in missing.items():
                effect = file_effect(path, language, names, book)
                found[key] = (effect.dropped, effect.changed) if effect is not None else None
            return found

        job = BackgroundJob(work)
        job.finished.connect(self._on_counted)
        job.failed.connect(self._on_count_failed)
        job.start()

    def _on_counted(self, found: object) -> None:
        self._counting = False
        assert isinstance(found, dict)
        if len(self._effects) > _EFFECTS_KEPT:
            self._effects = {}
        self._effects.update(found)
        self.refresh()

    def _on_count_failed(self, error: object) -> None:
        self._counting = False

    # The Cleanup row's menus

    @Slot(str)
    def add_rule_set(self, name: str) -> None:
        """A rule set added to this place's own."""
        if self._workspace.key is not None and not self._workspace.locked:
            self._set(cleanup={**self._options().cleanup, name: RuleSetUse.USED})

    @Slot(str)
    def edit_rule_sets(self, name: str = "") -> None:
        self.editor_asked.emit(name)

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
                reasons += [unavailable(phase, ai_model(finished)) for phase in missing_phases(finished)[:1]]
                joined = tr("subtitles.list.steps_separator").join(steps)
                if finished.target is not None and not (
                    work is not None and finished in work.finished and left_as_it_was(work, finished)
                ):
                    joined = tr("subtitles.list.to_file", steps=joined, file=finished.target.name)
                report = kept_sync(work, finished) if work is not None and finished in work.finished else None
                plan.append(
                    {
                        "code": code(finished.language),
                        "steps": joined,
                        "cannot": tr("common.list_separator").join(reasons),
                        "found": sync_found(report) if report is not None else "",
                        "review": report is not None and report.needs_review,
                    }
                )
            for finished in work.written_earlier if work is not None else ():
                assert finished.target is not None
                plan.append(
                    {
                        "code": code(finished.language),
                        "steps": tr("subtitles.written_earlier", file=finished.target.name),
                        "cannot": "",
                        "muted": True,
                    }
                )
            for subtitle in work.not_added if work is not None and not plan else ():
                plan.append({"code": code(subtitle.language), "steps": "", "cannot": tr("subtitles.not_added")})
            rows.append(
                {
                    "path": str(item.file.path),
                    "number": item_number(item),
                    "file": item.file.path.name,
                    "now": now,
                    "plan": plan,
                    "reference": tr("subtitles.list.reference", reference=reference_text(work.reference))
                    if work is not None and work.reference is not None
                    else "",
                }
            )
        return rows


def _is_number(text: str) -> bool:
    try:
        return float(text) >= 0
    except ValueError:
        return False


def _file_label(item: MediaItem) -> str:
    return item_number(item) or item.file.path.name


def _files_text(files: list[MediaItem]) -> str:
    """One file by its number, several by their count."""
    return _file_label(files[0]) if len(files) == 1 else tr_plural("cleanup.files", len(files))


def unavailable(phase: str, model: str = "") -> str:
    """ "Sync is not available in this version yet." A phase that needs a program, the AI server or a model says
    which."""
    if phase in NEEDS:
        return tr(f"subtitles.needs.{phase}", backend=backend_name(), model=model)
    return tr("subtitles.unavailable", step=tr(f"jobs.phase.{phase}"))
