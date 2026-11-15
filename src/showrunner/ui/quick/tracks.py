"""What the Overview and Tracks places draw, as plain lists and dicts for QML: the batch's track columns (one per
signature, plus one per kind of paired subtitle file), each file's tracks as its plans leave them, the rule list in
words and the selected file's changes.

Everything here reads the plans and the options; nothing decides a plan. A file whose live plan has not arrived yet,
or whose track plan was refused or blocked, is shown with its tracks as they are, since that is what Apply leaves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from showrunner.app.batches.choices import TrackChoice, TrackSignature, choice_of, signature_of
from showrunner.app.jobs.counts import count_changes
from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaItem, SubtitleFile
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
    TrackPlan,
    TrackRule,
    TracksOptions,
    matches,
    stand_in,
)
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.sheet.format import size_text

KINDS = (TrackKind.AUDIO, TrackKind.SUBTITLE)
FLAGS = ("default", "forced")
_FLAG_TESTS = ("default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original")


@dataclass(frozen=True, slots=True)
class Column:
    """One chip, card group or matrix column: the tracks of a signature, or the paired files of one kind (then
    `signature` is that of the track they are planned as once added)."""

    signature: TrackSignature
    paired: PairedFile | None = None


@dataclass(frozen=True, slots=True)
class Seen:
    """One track of a file as its plan leaves it: kept, dropped or added (a paired file), with the flags after."""

    track: Track
    external: SubtitleFile | None
    state: str
    flags: TrackFlags


def code(language: Language | None) -> str:
    return language.alpha3.upper() if language is not None else NO_LANGUAGE.upper()


def _signature_code(signature: TrackSignature) -> str:
    return code(Language.parse(signature.language)) if signature.language != NO_LANGUAGE else NO_LANGUAGE.upper()


def _codec(signature: TrackSignature) -> str:
    return " ".join(
        p for p in (codec_display(signature.codec, ObjectAudio.NONE), channel_layout(signature.channels)) if p
    )


def columns(items: Sequence[MediaItem]) -> list[Column]:
    """Audio signatures, then subtitle signatures, each in the order first seen, then the kinds of paired file."""
    found: dict[TrackSignature, None] = {}
    for kind in KINDS:
        for item in items:
            found.update(dict.fromkeys(TrackSignature.of(t) for t in item.file.tracks if t.kind is kind))
    paired: dict[PairedFile, TrackSignature] = {}
    for item in items:
        for index, subtitle in enumerate(item.subtitles):
            paired.setdefault(PairedFile.of(subtitle), TrackSignature.of(stand_in(subtitle, index)))
    return [Column(s) for s in found] + [Column(s, p) for p, s in paired.items()]


def seen(item: MediaItem, file: FilePreview | None) -> list[Seen]:
    """The file's tracks in file order, then the paired files added, as the track plan leaves them."""
    stage = file.plan_for("tracks") if file is not None else None
    plan = stage.plan if stage is not None else None
    if not isinstance(plan, TrackPlan):
        return [Seen(t, None, "kept", t.flags) for t in item.file.tracks]
    rows = [Seen(k.track, k.external, "added" if k.external else "kept", k.flags) for k in plan.kept]
    rows += [Seen(d.track, d.external, "dropped", d.track.flags) for d in plan.dropped]
    return sorted(rows, key=lambda s: (s.external is not None, abs(s.track.id)))


def cell(column: Column, item: MediaItem, tracks: Sequence[Seen]) -> dict[str, object]:
    """One file under one column: kept, dropped, added, paired (beside the video, not added) or missing."""
    if column.paired is not None:
        found = next((s for s in tracks if s.external and PairedFile.of(s.external) == column.paired), None)
        if found is None:
            beside = any(PairedFile.of(sub) == column.paired for sub in item.subtitles)
            return {"state": "paired" if beside else "missing", "default": False, "forced": False}
    else:
        found = next((s for s in tracks if s.external is None and TrackSignature.of(s.track) == column.signature), None)
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

    @classmethod
    def build(cls, items: Sequence[MediaItem], options: TracksOptions, files: Sequence[FilePreview]) -> BatchView:
        return cls(items, options, {str(f.item.file.path): f for f in files}, columns(items))

    def file(self, item: MediaItem) -> FilePreview | None:
        return self.files.get(str(item.file.path))

    def cells(self, item: MediaItem) -> list[dict[str, object]]:
        tracks = seen(item, self.file(item))
        firsts = _first_defaults(self.options, self.cols)
        result = []
        for column in self.cols:
            found = cell(column, item, tracks)
            first = firsts.get(column.signature.kind)
            # A default that lands on another track than the first choice of its kind: the choice has no track here.
            found["fallback"] = bool(found["default"]) and first is not None and first != column.signature
            result.append(found)
        return result

    def choice(self, index: int) -> TrackChoice:
        return choice_of(self.options, self.cols[index].signature)

    # Columns: chips, matrix headers

    def headers(self) -> list[dict[str, object]]:
        grid = [self.cells(item) for item in self.items]
        total = len(self.items)
        headers = []
        for index, column in enumerate(self.cols):
            states = [row[index]["state"] for row in grid if row[index]["state"] != "missing"]
            choice = self.choice(index)
            if column.paired is not None:
                state = "added" if "added" in states else "dropped" if "dropped" in states else "paired"
            else:
                state = "dropped" if states and all(s == "dropped" for s in states) else "kept"
            present = len(states)
            signature = column.signature
            headers.append(
                {
                    "id": index,
                    "kind": signature.kind.value,
                    "code": _signature_code(signature),
                    "title": tr("tracks.paired_file", format=column.paired.format)
                    if column.paired
                    else _codec(signature),
                    "name": signature.name,
                    "paired": column.paired is not None,
                    "state": state,
                    "button": tr(f"tracks.state.{state}"),
                    "default": choice.default,
                    "forced": choice.forced,
                    # Flags apply to a paired file only once it is added.
                    "flags": column.paired is None or state == "added",
                    "count": tr("tracks.present", present=present, total=total) if present < total else "",
                }
            )
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
                {**c, "code": _signature_code(col.signature), "added": col.paired is not None}
                for c, col in zip(cells, self.cols, strict=True)
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
                    "changes_text": tr_plural("tracks.changes", changes) if changes else tr("tracks.no_changes"),
                    "warning": self.warning(item),
                }
            )
        return rows

    def changes(self, item: MediaItem) -> int:
        file = self.file(item)
        return sum(count_changes(file).values()) if file is not None else 0

    def warning(self, item: MediaItem) -> str:
        """Why this file does not follow the batch: a refused or unwritable plan, or a choice with no track here."""
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
            if any(TrackSignature.of(s.track) == first for s in tracks if s.external is None):
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
                    or (column.paired is None and s.external is None and TrackSignature.of(s.track) == column.signature)
                ),
                None,
            )
            choice = self.choice(index)
            old = track.name if track is not None else ""
            new = names.get(track.id, "") if track is not None else ""
            cards.append(
                {
                    "id": index,
                    "kind": column.signature.kind.value,
                    "code": _signature_code(column.signature),
                    "title": tr("tracks.paired_file", format=column.paired.format)
                    if column.paired
                    else _codec(column.signature),
                    "state": found["state"],
                    "name": new or old,
                    "renamed": bool(new),
                    "was": tr("tracks.was", name=old) if new and old else tr("tracks.as_is") if old else "",
                    "default": choice.default,
                    "forced": choice.forced,
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
                    "cards": of_kind,
                }
            )
        return groups

    # Rules

    def rules(self) -> list[dict[str, object]]:
        signatures = [c.signature for c in self.cols]
        rules = []
        for index, rule in enumerate(self.options.rules):
            fits = sum(
                any(
                    matches(rule.match, t, flags_from_name=self.options.flags_from_names) for t in _all(i, self.options)
                )
                for i in self.items
            )
            rules.append(
                {
                    "enabled": rule.enabled,
                    "from_choice": rule.from_choice,
                    "parts": rule_parts(rule, signature_of(rule, signatures), self.options.rules[:index]),
                    "fits": tr_plural("tracks.rule.fits", fits),
                    "source": tr("tracks.rule.from_matrix") if rule.from_choice else tr("tracks.rule.written"),
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
    parts = [_part(tr(f"tracks.rule.verb.{rule.verdict.value}")), _part(tr(f"tracks.rule.kind.{match.kind.value}"))]
    if signature is not None:
        parts += [_part(tr("tracks.rule.in")), _part(_signature_code(signature), True)]
        # The name tells most tracks apart; an unnamed track is told by its codec.
        if signature.name:
            parts += [_part(tr("tracks.rule.named")), _part(signature.name, True)]
        else:
            parts.append(_part(_codec(signature)))
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
    for flag in FLAGS:
        if getattr(rule, flag) is FlagShape.FIRST:
            fallback = any(
                r.enabled and getattr(r, flag) is FlagShape.FIRST and _kinds_meet(r.match.kind, match.kind)
                for r in above
            )
            parts.append(_part(tr(f"tracks.rule.{flag}_fallback" if fallback else f"tracks.rule.{flag}")))
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
