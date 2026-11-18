"""What the Overview and Tracks places draw, as plain lists and dicts for QML: the batch's track columns (one per
signature, plus one per kind of paired subtitle file), each file's tracks as its plans leave them, the rule list in
words and the selected file's changes.

Everything here reads the plans and the options; nothing decides a plan. A file whose live plan has not arrived yet,
or whose track plan was refused or blocked, is shown with its tracks as they are, since that is what Apply leaves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from showrunner.app.batches.choices import (
    TrackChoice,
    TrackGroups,
    TrackSignature,
    choice_index,
    choice_of,
    in_order,
    name_of_rule,
    named,
    signature_of,
)
from showrunner.app.jobs.counts import count_changes
from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.core.language import Language
from showrunner.core.media import Episode, Extra, MediaItem, SubtitleFile
from showrunner.core.naming.names import channel_layout, codec_display
from showrunner.core.track import ObjectAudio, Track, TrackFlags, TrackKind
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.mux.options import Original
from showrunner.stages.tracks import (
    NO_LANGUAGE,
    FlagShape,
    FlagTest,
    KindTest,
    PairedFile,
    PlanRefused,
    SourceTest,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    deciding,
    matches,
    stand_in,
)
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.sheet.format import size_text

KINDS = (TrackKind.AUDIO, TrackKind.SUBTITLE)
FLAGS = ("default", "forced")
_FLAG_TESTS = ("default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original")
# What a track is, as a signature holds it, in the order a chip names it.
_WHAT = ("commentary", "hearing_impaired", "visual_impaired", "forced")


@dataclass(frozen=True, slots=True)
class Column:
    """One chip, card group or matrix column: the tracks of a signature, or the paired files of one kind (then
    `signature` is that of the track they are planned as once added)."""

    signature: TrackSignature
    paired: PairedFile | None = None


@dataclass(frozen=True, slots=True)
class Received:
    """What a season, an episode or a movie receives from above, to mark where a choice comes from. An origin is the
    kind of place that set a rule (`show`, `season`, `selection`), or "" for the batch's own."""

    origins: Sequence[str] = ()  # per rule of the batch's track options
    tracks: TracksOptions = field(default_factory=TracksOptions)  # the track options received
    received_origins: Sequence[str] = ()  # per rule of `tracks`
    # The paired files added: the kind of place above that set them, or, when the batch set them itself, the kind of
    # place whose paired files it overrides; "" for neither.
    paired_from: str = ""
    paired_over: str = ""


@dataclass(frozen=True, slots=True)
class Seen:
    """One track of a file as its plan leaves it: kept, dropped or added (a paired file), with the flags after."""

    track: Track
    external: SubtitleFile | None
    state: str
    flags: TrackFlags
    rule: TrackRule | None = None  # the rule that drops it


def code(language: Language | None) -> str:
    """The badge's text: the 3-letter code, then the script and the region when the tag has them (`POR-BR`)."""
    if language is None:
        return NO_LANGUAGE.upper()
    return "-".join(part for part in (language.alpha3, language.script, language.region) if part).upper()


def _tag_code(tag: str) -> str:
    return code(Language.parse(tag)) if tag != NO_LANGUAGE else NO_LANGUAGE.upper()


def _signature_code(signature: TrackSignature) -> str:
    return _tag_code(signature.language)


def _shown_code(signature: TrackSignature, choice: TrackChoice) -> str:
    """The badge of a chip, card or column: the language the choice gives the tracks, else the one they have."""
    return _tag_code(choice.language or signature.language)


def _codec(signature: TrackSignature) -> str:
    return " ".join(
        p for p in (codec_display(signature.codec, ObjectAudio.NONE), channel_layout(signature.channels)) if p
    )


def _what(signature: TrackSignature) -> list[str]:
    return [flag for flag in _WHAT if getattr(signature, flag)]


def columns(
    items: Sequence[MediaItem], groups: TrackGroups | None = None, options: TracksOptions | None = None
) -> list[Column]:
    """Audio signatures, then subtitle signatures, each in the order first seen, then the kinds of paired file; with
    `options`, each kind in the order its tracks get in the new files."""
    groups = groups if groups is not None else TrackGroups.of(items, flags_from_names=True)
    found: dict[TrackSignature, None] = {}
    for kind in KINDS:
        for item in items:
            found.update(dict.fromkeys(groups.signature(t) for t in item.file.tracks if t.kind is kind))
    paired: dict[PairedFile, TrackSignature] = {}
    for item in items:
        for index, subtitle in enumerate(item.subtitles):
            paired.setdefault(PairedFile.of(subtitle), groups.signature(stand_in(subtitle, index)))
    cols = [Column(s) for s in found] + [Column(s, p) for p, s in paired.items()]
    return [cols[n] for n in in_order([c.signature for c in cols], options)] if options is not None else cols


def seen(item: MediaItem, file: FilePreview | None) -> list[Seen]:
    """The file's tracks, then the paired files added, as the track plan leaves them: the tracks that stay in the new
    file's order, each dropped one where the file has it."""
    stage = file.plan_for("tracks") if file is not None else None
    plan = stage.plan if stage is not None else None
    if not isinstance(plan, TrackPlan):
        return [Seen(t, None, "kept", t.flags) for t in item.file.tracks]
    staying = [Seen(k.track, k.external, "added" if k.external else "kept", k.flags) for k in plan.kept]
    rows = staying + [Seen(d.track, d.external, "dropped", d.track.flags, d.rule) for d in plan.dropped]
    in_file = sorted(rows, key=lambda s: (s.external is not None, abs(s.track.id)))
    # The places of the tracks that stay, in file order, take them in the order of the new file.
    new_order = iter(staying)
    return [s if s.state == "dropped" else next(new_order) for s in in_file]


def by_signature(tracks: Sequence[Seen], groups: TrackGroups) -> dict[TrackSignature, Seen]:
    """A file's embedded tracks by signature, the first in file order for each."""
    found: dict[TrackSignature, Seen] = {}
    for s in tracks:
        if s.external is None:
            found.setdefault(groups.signature(s.track), s)
    return found


def cell(
    column: Column, item: MediaItem, tracks: Sequence[Seen], signatures: dict[TrackSignature, Seen]
) -> dict[str, object]:
    """One file under one column: kept, dropped, added, paired (beside the video, not added) or missing.
    `signatures` is the file's `by_signature`, made once for all its columns."""
    if column.paired is not None:
        found = next((s for s in tracks if s.external and PairedFile.of(s.external) == column.paired), None)
        if found is None:
            beside = any(PairedFile.of(sub) == column.paired for sub in item.subtitles)
            return {"state": "paired" if beside else "missing", "default": False, "forced": False}
    else:
        found = signatures.get(column.signature)
        if found is None:
            return {"state": "missing", "default": False, "forced": False}
    kept = found.state != "dropped"
    return {"state": found.state, "default": kept and found.flags.default, "forced": kept and found.flags.forced}


def _first_defaults(options: TracksOptions, cols: Sequence[Column]) -> dict[TrackKind, TrackSignature]:
    """Per kind, the signature whose choice is tried first for the default flag."""
    firsts: dict[TrackKind, TrackSignature] = {}
    for rule in options.rules:
        signature = signature_of(rule, [c.signature for c in cols])
        if rule.enabled and rule.default is FlagShape.FIRST and signature is not None:
            firsts.setdefault(signature.kind, signature)
    return firsts


@dataclass(frozen=True, slots=True)
class BatchView:
    """Everything the two places draw for one batch, built once per plan or choice."""

    items: Sequence[MediaItem]
    options: TracksOptions
    files: dict[str, FilePreview]  # by path
    cols: list[Column]
    grouping: TrackGroups = field(default_factory=TrackGroups)
    firsts: dict[TrackKind, TrackSignature] = field(default_factory=dict)
    # Why a file's tracks could not be read, by path; those files show it instead of a plan.
    failures: Mapping[str, str] = field(default_factory=dict, compare=False)
    received: Received = field(default_factory=Received)
    # Each file's cells, built on first use: the headers, the rows and the Inspector all read them.
    _cells: dict[str, list[dict[str, object]]] = field(default_factory=dict, compare=False, repr=False)
    # Each signature's track names, file by file, built on first use.
    _names: dict[TrackSignature, list[tuple[MediaItem, str]]] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def build(
        cls,
        items: Sequence[MediaItem],
        options: TracksOptions,
        files: Sequence[FilePreview],
        failures: Mapping[str, str] | None = None,
        received: Received | None = None,
    ) -> BatchView:
        groups = TrackGroups.of(items, options.flags_from_names)
        cols = columns(items, groups, options)
        by_path = {str(f.item.file.path): f for f in files}
        firsts = _first_defaults(options, cols)
        return cls(items, options, by_path, cols, groups, firsts, failures or {}, received or Received())

    def file(self, item: MediaItem) -> FilePreview | None:
        return self.files.get(str(item.file.path))

    def was_read(self, item: MediaItem) -> bool:
        """Whether the file's tracks are known: not when they could not be read, nor when a cancelled read did not
        reach the file."""
        return str(item.file.path) not in self.failures and bool(item.file.tracks)

    def cells(self, item: MediaItem) -> list[dict[str, object]]:
        key = str(item.file.path)
        if key not in self._cells:
            self._cells[key] = self._cells_of(item)
        return self._cells[key]

    def _cells_of(self, item: MediaItem) -> list[dict[str, object]]:
        tracks = seen(item, self.file(item))
        signatures = by_signature(tracks, self.grouping)
        result = []
        for column in self.cols:
            found = cell(column, item, tracks, signatures)
            first = self.firsts.get(column.signature.kind)
            # A default that lands on another track than the first choice of its kind: the choice has no track here.
            found["fallback"] = bool(found["default"]) and first is not None and first != column.signature
            result.append(found)
        return result

    def choice(self, index: int) -> TrackChoice:
        return choice_of(self.options, self.cols[index].signature)

    def place_mark(self, index: int) -> dict[str, str]:
        """Where a column's choice comes from: `from` names the place above that made it, `over` the place whose
        choice the batch's own one overrides, `short` either of them for a narrow column; all empty when the choice
        is the batch's own and nothing came from above, or when there is none."""
        column = self.cols[index]
        mark = self._mark(column.signature)
        return mark if any(mark.values()) or column.paired is None else self._paired_mark(column.paired)

    def _paired_mark(self, paired: PairedFile) -> dict[str, str]:
        """Where a paired file chip's adding comes from, when no rule decides it: marked from above while it is
        added, and as an override where the batch's own list adds or leaves it unlike what it receives."""
        received, added = self.received, paired in self.options.add_paired
        if received.paired_from and added:
            origin = received.paired_from
            return {"from": tr(f"place.from.{origin}"), "over": "", "short": tr(f"place.short.from.{origin}")}
        if received.paired_over and added != (paired in received.tracks.add_paired):
            return {"from": "", "over": tr(f"place.over.{received.paired_over}"), "short": tr("place.short.over")}
        return {"from": "", "over": "", "short": ""}

    def _mark(self, signature: TrackSignature) -> dict[str, str]:
        received = self.received
        at = choice_index(self.options.rules, signature)
        origin = received.origins[at] if at is not None and at < len(received.origins) else ""
        if origin:
            return {"from": tr(f"place.from.{origin}"), "over": "", "short": tr(f"place.short.from.{origin}")}
        given = choice_index(received.tracks.rules, signature) if at is not None else None
        above = received.received_origins[given] if given is not None and given < len(received.received_origins) else ""
        if not above:
            return {"from": "", "over": "", "short": ""}
        return {"from": "", "over": tr(f"place.over.{above}"), "short": tr("place.short.over")}

    def _named(self) -> dict[TrackSignature, list[tuple[MediaItem, str]]]:
        """Per signature, each file that has such a track with the name of its first one."""
        if not self._names:
            for item in self.items:
                firsts: dict[TrackSignature, str] = {}
                for track in item.file.tracks:
                    firsts.setdefault(self.grouping.signature(track), track.name)
                for signature, name in firsts.items():
                    self._names.setdefault(signature, []).append((item, name))
        return self._names

    def _label(self, column: Column) -> str:
        """What a chip says beside its codec: the name every file gives the track, else what the track is."""
        names = {name for _, name in self._named().get(column.signature, [])} if column.paired is None else set()
        if len(names) == 1 and "" not in names:
            return names.pop()
        separator = f" {tr('status.separator')} "
        return separator.join(tr(f"tracks.what.{flag}") for flag in _what(column.signature))

    def names(self, index: int) -> list[str]:
        """The ▾ list of a column: each file that has the track, by its number, with the track's name or that it has
        none. A file without the track is left out here; `missing` names those."""
        if not 0 <= index < len(self.cols) or self.cols[index].paired is not None:
            return []
        one_season = self._one_season()
        rows = []
        for item, name in self._named().get(self.cols[index].signature, []):
            number = file_label(item, one_season)
            rows.append(
                tr("tracks.names.row", number=number, name=name) if name else tr("tracks.names.none", number=number)
            )
        return rows

    def name_rows(self, index: int) -> list[dict[str, object]]:
        """The lines of a chip's ▾ list. Where the chip's tracks carry two or more names, one line per name, with the
        files that use it, and the line is `clickable`: a click keeps or drops the tracks with that name (a rule ahead
        of the chip's own choice). Else one line per file, as `names` has them, which no click acts on (one name is the
        chip's own choice, and a chip told apart by name has only that name). Names differing in case are one name,
        as the rule's name test ignores case."""
        if not 0 <= index < len(self.cols) or self.cols[index].paired is not None:
            return []
        column, one_season = self.cols[index], self._one_season()
        groups: dict[str, tuple[str, list[MediaItem]]] = {}
        for item, name in self._named().get(column.signature, []):
            groups.setdefault(name.casefold(), (name, []))[1].append(item)
        if len(groups) < 2 or column.signature.name is not None:
            return [_name_row(text) for text in self.names(index)]
        options = self.options
        active = [(n, rule) for n, rule in enumerate(options.rules) if rule.enabled]
        rows = []
        for key, (name, items) in groups.items():
            number = tr("common.list_separator").join(file_label(i, one_season) for i in items)
            text = tr("tracks.names.row" if name else "tracks.names.none", number=number, name=name)
            signature = named(column.signature, name)
            tracks = [
                t
                for i in items
                for t in i.file.tracks
                if self.grouping.signature(t) == column.signature and t.name.casefold() == key
            ]
            decided = [deciding(active, t, options.flags_from_names) for t in tracks]
            dropped = bool(decided) and all(d is not None and d[1].verdict is Verdict.DROP for d in decided)
            # The place's mark shows only where this name's own rule decides.
            owned = decided and decided[0] is not None and decided[0][0] == choice_index(options.rules, signature)
            mark = self._mark(signature) if owned else {"from": "", "over": "", "short": ""}
            state = tr(f"tracks.state.{'dropped' if dropped else 'kept'}")
            label = f"{text} {state} {mark['from'] or mark['over']}".strip()
            rows.append(_name_row(text, clickable=True, name=name, dropped=dropped, mark=mark, label=label))
        return rows

    def _one_season(self) -> bool:
        return len({(i.identity.show, i.identity.season) for i in self.items if isinstance(i.identity, Episode)}) <= 1

    def lacking(self, index: int) -> list[MediaItem]:
        """The files that were read and have no such track. A file whose tracks were not read has none to show,
        which says nothing about whether it has this one, so it is in neither list."""
        if not 0 <= index < len(self.cols):
            return []
        return [item for item in self.items if self.was_read(item) and self.cells(item)[index]["state"] == "missing"]

    def held(self, index: int) -> list[MediaItem]:
        """The files whose plan is known and keeps a track that the column's choice drops: a plan that was refused
        (it would leave no audio) leaves the file as it is. Empty while the plan has not arrived, since every file
        would then look held."""
        if not 0 <= index < len(self.cols) or self.cols[index].paired is not None:
            return []
        if self.choice(index).verdict is not Verdict.DROP:
            return []
        return [
            item
            for item in self.items
            if self.was_read(item)
            and self.file(item) is not None
            and self.cells(item)[index]["state"] == "kept"
            and not self.kept_by_name(item, index)
        ]

    def kept_by_name(self, item: MediaItem, index: int) -> bool:
        """Whether a rule for one name of the column keeps the file's track on purpose, though the chip drops the rest:
        such a track is not one the plan holds back."""
        signature = self.cols[index].signature
        active = [(n, rule) for n, rule in enumerate(self.options.rules) if rule.enabled]
        for track in item.file.tracks:
            if self.grouping.signature(track) != signature:
                continue
            decided = deciding(active, track, self.options.flags_from_names)
            if decided is not None and decided[1].verdict is Verdict.KEEP and name_of_rule(decided[1], [signature]):
                return True
        return False

    def missing(self, index: int) -> str:
        """The line under a column's names that says which files lack the track; empty when none does."""
        lacking = self.lacking(index)
        if not lacking:
            return ""
        one_season = self._one_season()
        files = tr("common.list_separator").join(file_label(i, one_season) for i in lacking)
        return tr("tracks.names.missing", files=files)

    def held_note(self, index: int) -> str:
        """The line above a column's names that says which files keep the track though the choice drops it, and why
        (the plan of such a file was refused); empty when none does."""
        held = self.held(index)
        if not held:
            return ""
        one_season = self._one_season()
        files = tr("common.list_separator").join(file_label(i, one_season) for i in held)
        why = "; ".join(dict.fromkeys(w for i in held if (w := self.warning(i))))
        return tr("tracks.names.held", files=files, why=why)

    # Columns: chips, matrix headers

    def headers(self) -> list[dict[str, object]]:
        grid = [self.cells(item) for item in self.items]
        # Rows of files that were read: an unread file counts neither as having a track nor as lacking it.
        read = [row for item, row in zip(self.items, grid, strict=True) if self.was_read(item)]
        headers = []
        for index, column in enumerate(self.cols):
            states = [row[index]["state"] for row in grid if row[index]["state"] != "missing"]
            choice = self.choice(index)
            if column.paired is not None:
                state = "added" if "added" in states else "dropped" if "dropped" in states else "paired"
            else:
                # What the choice says shows at once, before the plan arrives and also where the plan keeps the track.
                dropped = choice.verdict is Verdict.DROP or (bool(states) and all(s == "dropped" for s in states))
                state = "dropped" if dropped else "kept"
            lacking = sum(1 for row in read if row[index]["state"] == "missing")
            held = len(self.held(index))
            signature = column.signature
            headers.append(
                {
                    "id": index,
                    "kind": signature.kind.value,
                    "code": _shown_code(signature, choice),
                    # The language the tracks have and the tag the choice gives them (empty when it gives none), for
                    # the picker and for a badge that says it was changed.
                    "language": signature.language,
                    "language_set": choice.language,
                    "title": tr("tracks.paired_file", format=column.paired.format)
                    if column.paired
                    else _codec(signature),
                    "name": self._label(column),
                    # The ▾ that lists each file's name for the track, and the files that lack it.
                    "names": column.paired is None or lacking > 0,
                    "paired": column.paired is not None,
                    "state": state,
                    "button": tr(f"tracks.state.{state}"),
                    "default": choice.default,
                    "forced": choice.forced,
                    **self.place_mark(index),
                    # Flags apply to a paired file only once it is added.
                    "flags": column.paired is None or state == "added",
                    "count": f" {tr('status.separator')} ".join(
                        [tr_plural("tracks.missing", lacking)] * bool(lacking)
                        + [tr_plural("tracks.held", held)] * bool(held)
                    ),
                }
            )
        # A kind with one column has no order to set.
        for header in headers:
            header["movable"] = sum(c.signature.kind.value == header["kind"] for c in self.cols) > 1
        return headers

    def groups(self) -> list[dict[str, object]]:
        """The headers split by kind, for the chip rows: Audio, then Subtitles with the paired files."""
        headers = self.headers()
        return [
            {
                "label": tr(f"tracks.kind.{kind.value}"),
                "icon": "audio" if kind is TrackKind.AUDIO else "subs",
                "chips": [h for h in headers if h["kind"] == kind.value],
            }
            for kind in KINDS
        ]

    # Rows: one per file

    def rows(self) -> list[dict[str, object]]:
        kinds = [c.signature.kind for c in self.cols]
        rows = []
        for item in self.items:
            cells = self.cells(item)
            pills = [
                {**c, "code": _shown_code(col.signature, self.choice(index)), "added": col.paired is not None}
                for index, (c, col) in enumerate(zip(cells, self.cols, strict=True))
                if c["state"] not in ("missing", "paired")
            ]
            changes = self.changes(item)
            rows.append(
                {
                    "path": str(item.file.path),
                    "number": item_number(item),
                    "title": item_title(item),
                    "file": item.file.path.stem,
                    "cells": cells,
                    "audio": [p for p, k in zip(pills, _pill_kinds(cells, kinds), strict=True) if k is TrackKind.AUDIO],
                    "subtitles": [
                        p for p, k in zip(pills, _pill_kinds(cells, kinds), strict=True) if k is TrackKind.SUBTITLE
                    ],
                    "changes": changes,
                    "changes_text": tr_plural("tracks.changes", changes)
                    if changes
                    else tr("tracks.no_changes" if self.was_read(item) else "tracks.not_read"),
                    "warning": self.warning(item),
                }
            )
        return rows

    def changes(self, item: MediaItem) -> int:
        file = self.file(item)
        return sum(count_changes(file).values()) if file is not None else 0

    def failure(self, item: MediaItem) -> str:
        """Why the file's tracks could not be read, worded as the library's mark words it; empty when they could."""
        reason = self.failures.get(str(item.file.path))
        return tr("library.tip.failed", reason=reason) if reason is not None else ""

    def warning(self, item: MediaItem) -> str:
        """Why this file does not follow the batch: unreadable, a refused or unwritable plan, or a choice with no
        track here."""
        if failed := self.failure(item):
            return failed
        file = self.file(item)
        stage = file.plan_for("tracks") if file is not None else None
        if stage is not None and isinstance(stage.plan, PlanRefused):
            return refused_text(stage.plan)
        if file is not None and file.outcome is FileOutcome.NEEDS_REMUX:
            return tr("tracks.warning.needs_remux")
        if file is not None and file.outcome is FileOutcome.UNWRITTEN:
            return tr("tracks.warning.unwritten")
        tracks = seen(item, file)
        firsts = _first_defaults(self.options, self.cols)
        for kind, first in firsts.items():
            if any(self.grouping.signature(s.track) == first for s in tracks if s.external is None):
                continue
            column = next(c for c in self.cols if c.signature == first)
            if column.paired is not None:
                continue
            missing = language_kind(first.language, kind)
            fallback = next(
                (s for s in tracks if s.track.kind is kind and s.state != "dropped" and s.flags.default), None
            )
            if fallback is None:
                return tr("tracks.warning.missing", missing=missing)
            other = language_kind(fallback.track.language.ietf if fallback.track.language else NO_LANGUAGE, kind)
            return tr("tracks.warning.fallback", missing=missing, other=other)
        return ""

    # Movie cards

    def cards(self, item: MediaItem) -> list[dict[str, object]]:
        """The movie's tracks as cards, by kind: the choice on each, and its name now and after."""
        cells = self.cells(item)
        names = new_names(self.file(item))
        tracks = seen(item, self.file(item))
        cards = []
        for index, (column, found) in enumerate(zip(self.cols, cells, strict=True)):
            if found["state"] == "missing":
                continue
            track = next(
                (
                    s.track
                    for s in tracks
                    if (column.paired and s.external and PairedFile.of(s.external) == column.paired)
                    or (
                        column.paired is None
                        and s.external is None
                        and self.grouping.signature(s.track) == column.signature
                    )
                ),
                None,
            )
            choice = self.choice(index)
            mark = self.place_mark(index)
            del mark["short"]  # a card has room for the whole mark
            old = track.name if track is not None else ""
            new = names.get(track.id, "") if track is not None else ""
            cards.append(
                {
                    "id": index,
                    "kind": column.signature.kind.value,
                    "code": _shown_code(column.signature, choice),
                    "language": column.signature.language,
                    "language_set": choice.language,
                    "title": tr("tracks.paired_file", format=column.paired.format)
                    if column.paired
                    else _codec(column.signature),
                    "state": found["state"],
                    "name": new or old,
                    "renamed": bool(new),
                    "was": tr("tracks.was", name=old) if new and old else tr("tracks.as_is") if old else "",
                    "default": choice.default,
                    "forced": choice.forced,
                    **mark,
                    "is_default": found["default"],
                    "is_forced": found["forced"],
                }
            )
        return cards

    def card_groups(self, item: MediaItem) -> list[dict[str, object]]:
        cards = self.cards(item)
        groups = []
        for kind in KINDS:
            of_kind = [c for c in cards if c["kind"] == kind.value]
            before = sum(1 for c in of_kind if c["state"] != "paired" and c["state"] != "added")
            after = sum(1 for c in of_kind if c["state"] in ("kept", "added"))
            groups.append(
                {
                    "label": tr(f"tracks.kind.{kind.value}"),
                    "icon": "audio" if kind is TrackKind.AUDIO else "subs",
                    "count": tr("tracks.before_after", before=before, after=after),
                    "cards": [{**c, "movable": len(of_kind) > 1} for c in of_kind],
                }
            )
        return groups

    # Rules

    def fits(self, rule: TrackRule) -> int:
        """How many of the batch's files have a track the rule's match fits."""
        flags = self.options.flags_from_names
        return sum(
            any(matches(rule.match, t, flags_from_name=flags) for t in _all(i, self.options)) for i in self.items
        )

    def rules(self) -> list[dict[str, object]]:
        signatures = [c.signature for c in self.cols]
        rules = []
        origins = self.received.origins
        for index, rule in enumerate(self.options.rules):
            fits = self.fits(rule)
            origin = origins[index] if index < len(origins) else ""
            rules.append(
                {
                    "enabled": rule.enabled,
                    "from_choice": rule.from_choice,
                    # A rule from above is changed where it was set; here it only shows what it decides.
                    "inherited": bool(origin),
                    "from": tr(f"place.from.{origin}") if origin else "",
                    "label": rule.label,
                    "parts": rule_parts(
                        rule,
                        signature_of(rule, signatures) or name_of_rule(rule, signatures),
                        self.options.rules[:index],
                    ),
                    "fits": tr_plural("tracks.rule.fits", fits),
                    "source": tr(
                        "tracks.rule.written"
                        if not rule.from_choice
                        else "tracks.rule.from_name"
                        if name_of_rule(rule, signatures)
                        else "tracks.rule.from_matrix"
                    ),
                }
            )
        return rules

    # Inspector

    def inspector(self, item: MediaItem, original: Original) -> dict[str, object]:
        file = self.file(item)
        tracks = seen(item, file)
        names = new_names(file)
        title = new_title(file)
        changes = _what_changes(item, file, tracks, original)
        return {
            "name": item_title(item) or item.file.path.stem,
            "facts": _facts(item),
            "file": item.file.path.name,
            "count": sum(count_changes(file).values()) if file is not None else 0,
            "changes": changes,
            "unread": self.failure(item) or ("" if self.was_read(item) else tr("tracks.not_read")),
            "stays": tr("inspector.stays"),
            "title_now": item.file.title,
            "title_new": title,
            "title_placeholder": tr("inspector.title_empty"),
            "tracks": [
                {
                    "kind": s.track.kind.value,
                    "code": code(s.track.language),
                    "title": _track_title(s.track),
                    "name": s.track.name,
                    "new_name": names.get(s.track.id, ""),
                    "state": s.state,
                    # The label of the rule that drops it, when the rule has one.
                    "by": tr("inspector.dropped_by", rule=s.rule.label) if s.rule is not None and s.rule.label else "",
                    "default": s.state != "dropped" and s.flags.default,
                    "forced": s.state != "dropped" and s.flags.forced,
                }
                for s in tracks
            ],
            "track_count": tr(
                "inspector.track_count",
                before=sum(s.external is None for s in tracks),
                after=sum(s.state != "dropped" for s in tracks),
            ),
        }


def refused_text(plan: PlanRefused) -> str:
    what = tr("tracks.warning.and").join(tr(f"tracks.warning.{p.kind.value}") for p in plan.problems)
    return tr("tracks.warning.refused", what=what)


def _part(text: str, code: bool = False) -> dict[str, object]:
    return {"text": text, "code": code}


def rule_parts(
    rule: TrackRule, signature: TrackSignature | None, above: Sequence[TrackRule]
) -> list[dict[str, object]]:
    """A rule in words, in pieces: plain words, and codes (languages, codecs, names) that QML draws as badges.
    "Keep audio in TUR · default", "Keep audio in ENG · default if none above", "Drop subtitles flagged SDH"."""
    match = rule.match
    # A choice of nothing, which a nearer place makes to take back a choice it receives.
    blank = (
        rule.from_choice
        and rule.verdict is Verdict.PASS
        and not rule.language
        and FlagShape.FIRST not in (rule.default, rule.forced)
    )
    verb = "leave" if blank else rule.verdict.value
    parts = [_part(tr(f"tracks.rule.verb.{verb}")), _part(tr(f"tracks.rule.kind.{match.kind.value}"))]
    if signature is not None:
        parts += [_part(tr("tracks.rule.in")), _part(_signature_code(signature), True), _part(_codec(signature))]
        parts += [_part(tr("tracks.rule.flag_set", flag=tr(f"tracks.flag.{flag}"))) for flag in _what(signature)]
        # Inside the file goes without saying, as with the flags a group does not have.
        if signature.paired:
            parts.append(_part(tr("tracks.rule.source.paired")))
        # Only a group told apart by name carries one.
        if signature.name:
            parts += [_part(tr("tracks.rule.named")), _part(signature.name, True)]
        elif signature.name is not None:
            parts.append(_part(tr("tracks.rule.unnamed")))
    else:
        if match.languages:
            parts += [_part(tr("tracks.rule.in"))] + [_part(lang.upper(), True) for lang in match.languages]
        parts += [_part(c, True) for c in match.codecs]
        if match.min_channels or match.max_channels:
            parts.append(_part(_channels(match.min_channels, match.max_channels)))
        if match.name:
            parts += [
                _part(tr("tracks.rule.matching" if match.name_is_regex else "tracks.rule.named")),
                _part(match.name, True),
            ]
        for flag in _FLAG_TESTS:
            test = getattr(match, flag)
            if test is not FlagTest.ANY:
                parts.append(_part(tr(f"tracks.rule.flag_{test.value}", flag=tr(f"tracks.flag.{flag}"))))
        if match.source is not SourceTest.ANY:
            parts.append(_part(tr(f"tracks.rule.source.{match.source.value}")))
    for flag in FLAGS:
        if getattr(rule, flag) is FlagShape.FIRST:
            fallback = any(
                r.enabled and getattr(r, flag) is FlagShape.FIRST and _kinds_meet(r.match.kind, match.kind)
                for r in above
            )
            parts.append(_part(tr(f"tracks.rule.{flag}_fallback" if fallback else f"tracks.rule.{flag}")))
    if rule.language:
        parts += [_part(tr("tracks.rule.language")), _part(_tag_code(rule.language), True)]
    if blank:
        parts.append(_part(tr("tracks.rule.as_it_is")))
    return parts


def _kinds_meet(one: KindTest, other: KindTest) -> bool:
    return KindTest.ANY in (one, other) or one is other


def _channels(low: int, high: int) -> str:
    if low and low == high:
        return tr("tracks.rule.channels_exact", count=channel_layout(low))
    if low and high:
        return tr("tracks.rule.channels_between", low=channel_layout(low), high=channel_layout(high))
    return (
        tr("tracks.rule.channels_min", count=channel_layout(low))
        if low
        else tr("tracks.rule.channels_max", count=channel_layout(high))
    )


def _pill_kinds(cells: list[dict[str, object]], kinds: list[TrackKind]) -> list[TrackKind]:
    return [k for c, k in zip(cells, kinds, strict=True) if c["state"] not in ("missing", "paired")]


def _all(item: MediaItem, options: TracksOptions) -> list[Track]:
    """The file's tracks and the paired files added to it, as the rules see them."""
    added = [stand_in(s, i) for i, s in enumerate(item.subtitles) if PairedFile.of(s) in options.add_paired]
    return [*item.file.tracks, *added]


def item_number(item: MediaItem) -> str:
    return f"{item.identity.episode:02d}" if isinstance(item.identity, Episode) else ""


def _name_row(
    text: str,
    *,
    clickable: bool = False,
    name: str = "",
    dropped: bool = False,
    mark: Mapping[str, str] | None = None,
    label: str = "",
) -> dict[str, object]:
    """One line of a chip's list; `label` is what a screen reader says."""
    return {
        "text": text,
        "name": name,
        "clickable": clickable,
        "dropped": dropped,
        **(mark or {"from": "", "over": "", "short": ""}),
        "label": label or text,
    }


def file_label(item: MediaItem, one_season: bool) -> str:
    """How a list names a file: its episode number in one season, its season and episode in more, else its title."""
    identity = item.identity
    if not isinstance(identity, Episode):
        return item_title(item)
    if one_season:
        return item_number(item)
    return tr("inspector.episode_code", season=identity.season, episode=identity.episode)


def item_title(item: MediaItem) -> str:
    identity = item.identity
    if isinstance(identity, Episode):
        return identity.episode_title or tr("library.episode_untitled", number=identity.episode)
    return identity.title


def _facts(item: MediaItem) -> str:
    identity = item.identity
    parts = []
    if isinstance(identity, Episode):
        parts.append(tr("inspector.episode_code", season=identity.season, episode=identity.episode))
        parts.append(
            identity.show if identity.year is None else tr("library.movie", title=identity.show, year=identity.year)
        )
    elif isinstance(identity, Extra):
        parts.append(
            identity.show if identity.year is None else tr("library.movie", title=identity.show, year=identity.year)
        )
    elif identity.year is not None:
        parts.append(str(identity.year))
    parts.append(size_text(item.file.size))
    return f" {tr('status.separator')} ".join(p for p in parts if p)


def language_kind(language: str, kind: TrackKind) -> str:
    parsed = Language.parse(language) if language != NO_LANGUAGE else None
    name = parsed.name if parsed is not None else tr("tracks.no_language")
    return tr(f"tracks.language_kind.{kind.value}", language=name)


def _track_title(track: Track) -> str:
    return _codec(TrackSignature.of(track))


def _metadata(file: FilePreview | None) -> MetadataPlan | None:
    stage = file.plan_for("metadata") if file is not None else None
    return stage.plan if stage is not None and isinstance(stage.plan, MetadataPlan) else None


def new_names(file: FilePreview | None) -> dict[int, str]:
    plan = _metadata(file)
    return (
        {c.track_id: str(c.new) for c in plan.changes if c.prop is Property.NAME and c.track_id is not None}
        if plan
        else {}
    )


def new_title(file: FilePreview | None) -> str:
    plan = _metadata(file)
    return next((str(c.new) for c in plan.changes if c.prop is Property.TITLE), "") if plan else ""


def _what_changes(
    item: MediaItem, file: FilePreview | None, tracks: Sequence[Seen], original: Original
) -> list[dict[str, str]]:
    """The inspector's list, grouped like the design: the new file, the flags that move, the names."""
    stage = file.plan_for("tracks") if file is not None else None
    plan = stage.plan if stage is not None else None
    changes: list[dict[str, str]] = []
    if isinstance(plan, PlanRefused):
        changes.append({"icon": "alert", "text": refused_text(plan), "detail": ""})
    if isinstance(plan, TrackPlan) and plan.needs_remux:
        kept = sum(s.state != "dropped" for s in tracks)
        before = sum(s.external is None for s in tracks)
        if file is not None and file.outcome is FileOutcome.NEEDS_REMUX:
            detail = tr("inspector.new_file.cannot")
        else:
            detail = tr(f"inspector.new_file.{original.value}")
        changes.append({"icon": "film", "text": tr("inspector.new_file", kept=kept, total=before), "detail": detail})
    if isinstance(plan, TrackPlan) and plan.reordered:
        changes.append({"icon": "grip", "text": tr("inspector.order"), "detail": ""})
    if isinstance(plan, TrackPlan):
        for flag in FLAGS:
            moved = []
            for kind in (TrackKind.VIDEO, *KINDS):
                before = {
                    s.track.id
                    for s in tracks
                    if s.track.kind is kind and s.external is None and getattr(s.track.flags, flag)
                }
                after = [s for s in tracks if s.track.kind is kind and s.state != "dropped" and getattr(s.flags, flag)]
                if before != {s.track.id for s in after}:
                    moved.append(
                        language_kind(after[0].track.language.ietf if after[0].track.language else NO_LANGUAGE, kind)
                        if after
                        else tr(f"inspector.none_kind.{kind.value}")
                    )
            if moved:
                text = tr(f"inspector.flag.{flag}", tracks=tr("common.list_separator").join(moved))
                changes.append({"icon": "star" if flag == "default" else "subs", "text": text, "detail": ""})
    metadata = _metadata(file)
    if metadata is not None:
        titled = any(c.prop is Property.TITLE for c in metadata.changes)
        named = sum(c.prop is Property.NAME for c in metadata.changes)
        others = sum(
            c.prop not in (Property.TITLE, Property.NAME, Property.FLAG_DEFAULT, Property.FLAG_FORCED)
            for c in metadata.changes
        )
        if titled or named:
            key = "both" if titled and named else "title" if titled else "names"
            changes.append({"icon": "names", "text": tr_plural(f"inspector.names.{key}", named), "detail": ""})
        if others:
            changes.append({"icon": "names", "text": tr_plural("inspector.header_edits", others), "detail": ""})
    return changes
