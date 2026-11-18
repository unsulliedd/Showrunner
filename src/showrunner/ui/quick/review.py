"""What the Review place draws, as plain lists and dicts for QML: the run's changes grouped by kind, each group in or
out of the run, and one card per file with what changes in it.

Two plans come in. `run` is planned with the left-out groups emptied, as Apply will run it; `full` with every group
in, so a left-out group can still show what it would do. Files out of the run are in both plans and only out of the
counts here and of the job (`create_job(left_out_files=...)`): the excluded ones, saved with the workspace, and the
ones left out of this run alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import Path

from showrunner.app.batches.batch import Media
from showrunner.app.jobs.blocked import StageBlock, blocked_stages
from showrunner.app.jobs.counts import name_changes, track_changes
from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaItem
from showrunner.core.track import TrackFlags, TrackKind
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.mux.options import MuxOptions
from showrunner.stages.tracks import NO_LANGUAGE, TrackPlan, TracksOptions
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.names import blocked_lines
from showrunner.ui.quick.tracks import (
    KINDS,
    BatchView,
    Seen,
    code,
    item_number,
    item_title,
    language_kind,
    new_names,
    new_title,
    seen,
)

# The kinds of change of each group, in the order its card lists them.
LINES: dict[ChangeGroup, tuple[str, ...]] = {
    ChangeGroup.TRACKS: ("new_file", "order", "flags"),
    ChangeGroup.NAMES: ("titles", "names", "other"),
}
GROUP_ICONS = {ChangeGroup.TRACKS: "audio", ChangeGroup.NAMES: "names"}
FILTERS = ("all", "run", "look", "out")
# A file's state in Review: in the run, in it but needing a look, left out of this run alone, or excluded.
OUT_STATES = ("out", "excluded")
# What no stage of this version changes, listed under "Stays as it is".
STAYS = ("chapters", "attachments", "artwork")
_LOOK = (FileOutcome.REFUSED, FileOutcome.NEEDS_REMUX, FileOutcome.UNWRITTEN, FileOutcome.MISSING)


@dataclass(frozen=True, slots=True)
class ReviewInput:
    items: Sequence[MediaItem]
    media: Media
    tracks: TracksOptions
    mux: MuxOptions
    run: Sequence[FilePreview]  # empty until the run plan for the batch's files arrived
    full: Sequence[FilePreview]
    groups_out: Set[ChangeGroup] = frozenset()
    files_out: Set[Path] = frozenset()  # left out of this run alone
    excluded: Set[Path] = frozenset()  # out of every run until included again
    blocks: dict[str, StageBlock] = field(default_factory=dict)
    # Each file's own options, which differ from the open place's where it or a place between them chose otherwise.
    profiles: Mapping[Path, Profile] = field(default_factory=dict)
    mkvtoolnix_missing: bool = False
    filter: str = "all"
    failures: Mapping[str, str] = field(default_factory=dict)  # why a file's tracks could not be read, by path


def parts(file: FilePreview | None) -> dict[str, int]:
    """A file's changes by kind: the new file, its track order and the flags the rules move (Tracks and new files),
    then titles, track names and every other header edit (Names and flags). They add up to `count_changes`."""
    found = dict.fromkeys((key for keys in LINES.values() for key in keys), 0)
    if file is None:
        return found
    stage = file.plan_for("tracks")
    tracks = stage.plan if stage is not None and isinstance(stage.plan, TrackPlan) else None
    if tracks is not None:
        found["new_file"] = int(tracks.needs_remux)
        found["order"] = int(tracks.reordered)
        found["flags"] = track_changes(tracks) - found["new_file"] - found["order"]
    stage = file.plan_for("metadata")
    if stage is not None and isinstance(stage.plan, MetadataPlan):
        found["titles"] = sum(c.prop is Property.TITLE for c in stage.plan.changes)
        found["names"] = sum(c.prop is Property.NAME for c in stage.plan.changes)
        found["other"] = name_changes(stage.plan, tracks) - found["titles"] - found["names"]
    return found


def _group_count(found: dict[str, int], group: ChangeGroup) -> int:
    return sum(found[key] for key in LINES[group])


def _by_path(files: Sequence[FilePreview]) -> dict[Path, FilePreview]:
    return {f.item.file.path: f for f in files}


def _writing(given: ReviewInput, run: dict[Path, FilePreview]) -> tuple[list[MediaItem], list[MediaItem]]:
    """The files in the run, and of those the ones Apply writes: a file whose plans write nothing (MKVToolNix
    missing) is a look, not a run."""
    included = [i for i in given.items if i.file.path not in given.files_out and i.file.path not in given.excluded]
    return included, [i for i in included if (f := run.get(i.file.path)) is not None and f.writes]


def totals(given: ReviewInput) -> tuple[int, int]:
    """The changes Apply writes and the files they are in, without building Review's cards."""
    run = _by_path(given.run)
    per_file = [sum(parts(run.get(i.file.path)).values()) for i in _writing(given, run)[1]]
    return sum(per_file), sum(n > 0 for n in per_file)


def review(given: ReviewInput) -> dict[str, object]:
    run, full = _by_path(given.run), _by_path(given.full)
    included, writing = _writing(given, run)
    run_parts = {i.file.path: parts(run.get(i.file.path)) for i in given.items}
    full_parts = {i.file.path: parts(full.get(i.file.path)) for i in given.items}
    changes, files = totals(given)
    run_view = BatchView.build(given.items, given.tracks, given.run, given.failures)
    full_view = BatchView.build(given.items, given.tracks, given.full, given.failures)
    rows = [_row(given, item, run_view, full_view, run_parts[item.file.path]) for item in given.items]
    counts = {
        "all": len(rows),
        "run": sum(r["state"] not in OUT_STATES for r in rows),
        "look": sum(r["state"] == "look" for r in rows),
        "out": sum(r["state"] in OUT_STATES for r in rows),
    }
    stays = ([tr("review.stays.file_names")] if not given.mux.suffix else []) + [tr(f"review.stays.{k}") for k in STAYS]
    return {
        "count": changes,
        "files": files,
        "title": _changes_in(changes, files) if changes else tr("review.nothing"),
        "groups": [_group(given, group, included, writing, run_parts, full_parts) for group in ChangeGroup],
        "stays": stays,
        "filters": [{"key": key, "label": tr(f"review.filter.{key}"), "count": counts[key]} for key in FILTERS],
        "rows": [r for r in rows if _shown(given.filter, str(r["state"]))],
        "apply_text": tr("review.apply", changes=tr_plural("top.changes", changes), files=tr_plural("top.files", files))
        if changes
        else tr("review.apply_none"),
    }


def _changes_in(changes: int, files: int) -> str:
    return tr("top.changes_in", changes=tr_plural("top.changes", changes), files=tr_plural("top.files", files))


def _shown(which: str, state: str) -> bool:
    if which == "run":
        return state not in OUT_STATES
    if which == "out":
        return state in OUT_STATES
    return which in ("all", state)


def _group(
    given: ReviewInput,
    group: ChangeGroup,
    included: Sequence[MediaItem],
    writing: Sequence[MediaItem],
    run_parts: dict[Path, dict[str, int]],
    full_parts: dict[Path, dict[str, int]],
) -> dict[str, object]:
    """A group's card: in the run its lines count the run plan; left out they count what it would do, struck."""
    out = group in given.groups_out
    source, files = (full_parts, included) if out else (run_parts, writing)
    lines = [
        {"label": tr(f"review.line.{key}"), "count": count}
        for key in LINES[group]
        if (count := sum(source[i.file.path][key] for i in files))
    ]
    problems = _problems(given, group)
    if out:
        note = tr(f"review.left_out.{group.value}")
    elif not lines and not problems:
        note = tr(f"review.nothing.{group.value}")
    else:
        note = ""
    card: dict[str, object] = {
        "key": group.value,
        "icon": GROUP_ICONS[group],
        "title": tr(f"review.group.{group.value}"),
        "in_run": not out,
        "lines": lines,
        "note": note,
        "problems": problems,
        "program": given.mkvtoolnix_missing,
    }
    if group is ChangeGroup.TRACKS:
        card["original"] = given.mux.original.value
        card["original_text"] = _original(given.mux, given.mux.original.value)
        card["originals"] = [{"key": o, "label": _original(given.mux, o)} for o in ("recycle", "keep")]
    return card


def _original(mux: MuxOptions, original: str) -> str:
    return tr(f"review.original.{original}", folder=mux.keep_folder)


def _problems(given: ReviewInput, group: ChangeGroup) -> list[str]:
    """Why a group plans nothing or less than asked, worded, with a missing program first. What blocks a stage only
    in files whose own options differ from the open place's follows, naming those files."""
    found = [tr(f"review.program.{group.value}")] if given.mkvtoolnix_missing else []
    shown = _blocked(given.blocks, given.mux, group)
    found += shown
    by_options: dict[int, tuple[Profile, list[MediaItem]]] = {}
    for item in given.items:
        if (profile := given.profiles.get(item.file.path)) is not None:
            by_options.setdefault(id(profile), (profile, []))[1].append(item)
    for profile, items in by_options.values():
        lines = [
            line for line in _blocked(blocked_stages(profile), profile.for_stage("mux"), group) if line not in shown
        ]
        one = item_title(items[0]) or items[0].file.path.stem
        files = one if len(items) == 1 else tr_plural("review.files", len(items))
        found += [tr("review.blocked.in_files", files=files, problem=line) for line in lines]
    return found


def _blocked(blocks: Mapping[str, StageBlock], mux: MuxOptions, group: ChangeGroup) -> list[str]:
    found: list[str] = []
    if group is ChangeGroup.TRACKS:
        if block := blocks.get("tracks"):
            numbers = sorted({p.rule_index + 1 for p in block.rules})
            found.append(tr("review.blocked.rules", rules=tr("common.list_separator").join(map(str, numbers))))
        if block := blocks.get("mux"):
            found += [tr(f"review.blocked.{name.value}", folder=mux.keep_folder) for name in block.names]
    else:
        found += blocked_lines(blocks.get("metadata"))
    return found


# File cards


def _row(
    given: ReviewInput, item: MediaItem, run_view: BatchView, full_view: BatchView, found: dict[str, int]
) -> dict[str, object]:
    path = item.file.path
    run_file, full_file = run_view.file(item), full_view.file(item)
    warning = run_view.failure(item) or (run_view.warning(item) if run_file is not None else "")
    if path in given.excluded:
        state = "excluded"
    elif path in given.files_out:
        state = "out"
    elif warning or (run_file is not None and run_file.outcome in _LOOK):
        state = "look"
    else:
        state = "in"
    count = sum(found.values())
    every = parts(full_file)
    return {
        "path": str(path),
        "number": item_number(item),
        "title": item_title(item),
        "state": state,
        "count": count,
        "summary": _summary(found)
        if count
        else tr("review.file.nothing" if run_view.was_read(item) else "tracks.not_read"),
        "warning": warning,
        # One mark per group: amber where the group changes this file in the run, faint where it would but is out.
        "marks": [
            {
                "key": group.value,
                "on": _group_count(found, group) > 0 and state not in OUT_STATES,
                "out": _group_count(every, group) > 0 and (group in given.groups_out or state in OUT_STATES),
            }
            for group in ChangeGroup
        ],
        "detail": _detail(given, item, run_file, full_file),
    }


def _summary(found: dict[str, int]) -> str:
    """ "3 changes · new file, 2 flags"."""
    what = [
        tr(f"review.part.{key}") if key in ("new_file", "order") else tr_plural(f"review.part.{key}", n)
        for key, n in found.items()
        if n
    ]
    total = tr_plural("review.file.changes", sum(found.values()))
    return f"{total} {tr('status.separator')} {tr('common.list_separator').join(what)}"


def _pills(tracks: Sequence[Seen], kind: TrackKind, *, before: bool) -> list[dict[str, object]]:
    if before:
        return [
            {"code": code(s.track.language), "state": "kept", "added": False, **_flags(s, s.track.flags)}
            for s in tracks
            if s.track.kind is kind and s.external is None
        ]
    return [
        {"code": code(s.track.language), "state": s.state, "added": s.external is not None, **_flags(s, s.flags)}
        for s in tracks
        if s.track.kind is kind
    ]


def _flags(s: Seen, flags: TrackFlags) -> dict[str, bool]:
    kept = s.state != "dropped"
    return {"default": kept and flags.default, "forced": kept and flags.forced}


def _defaults(tracks: Sequence[Seen], *, before: bool) -> str:
    """ "English audio · no subtitles": the default track of each kind."""
    found = []
    for kind in KINDS:
        default = next(
            (
                s.track
                for s in tracks
                if s.track.kind is kind
                and (
                    s.external is None and s.track.flags.default if before else s.state != "dropped" and s.flags.default
                )
            ),
            None,
        )
        language = default.language.ietf if default is not None and default.language else NO_LANGUAGE
        found.append(language_kind(language, kind) if default is not None else tr(f"inspector.none_kind.{kind.value}"))
    return f" {tr('status.separator')} ".join(found)


def _detail(
    given: ReviewInput, item: MediaItem, run_file: FilePreview | None, full_file: FilePreview | None
) -> list[dict[str, object]]:
    """The expanded card: tracks before and after, the defaults, the file, the title and the track names. A row of a
    left-out group shows what the group would do, marked left out."""
    tracks_out = ChangeGroup.TRACKS in given.groups_out
    names_out = ChangeGroup.NAMES in given.groups_out
    after = seen(item, full_file if tracks_out else run_file)
    now = seen(item, None)
    rows: list[dict[str, object]] = []
    for kind in KINDS:
        before_pills = _pills(now, kind, before=True)
        after_pills = _pills(after, kind, before=False)
        if before_pills or after_pills:
            rows.append(_line(f"kind_{kind.value}", before_pills, after_pills, tracks_out, pills=True))
    before_defaults, after_defaults = _defaults(now, before=True), _defaults(after, before=False)
    if before_defaults != after_defaults:
        rows.append(_line("defaults", before_defaults, after_defaults, tracks_out))
    rows.append(
        _line(
            "file",
            item.file.path.name,
            _file_after(given, full_file if tracks_out else run_file),
            tracks_out,
            mono=True,
        )
    )
    named = full_file if names_out else run_file
    if title := new_title(named):
        rows.append(_line("title", item.file.title or tr("inspector.title_empty"), title, names_out, mono=True))
    if renamed := new_names(named):
        tracks = {t.id: t for t in item.file.tracks}
        before_names = [tracks[i].name for i in renamed if i in tracks]
        rows.append(_line("names", _joined(before_names), _joined(list(renamed.values())), names_out))
    return rows


def _joined(names: list[str]) -> str:
    return tr("common.list_separator").join(name or tr("review.unnamed") for name in names)


def _line(
    key: str, before: object, after: object, out: bool, *, pills: bool = False, mono: bool = False
) -> dict[str, object]:
    return {
        "label": tr(f"review.detail.{key}"),
        "before": before,
        "after": after,
        "out": out,
        "pills": pills,
        "mono": mono,
    }


def _file_after(given: ReviewInput, file: FilePreview | None) -> str:
    stage = file.plan_for("tracks") if file is not None else None
    plan = stage.plan if stage is not None else None
    if file is not None and file.outcome is FileOutcome.NEEDS_REMUX:
        return tr("inspector.new_file.cannot")
    if isinstance(plan, TrackPlan) and plan.needs_remux:
        profile = given.profiles.get(file.item.file.path) if file is not None else None
        mux = profile.for_stage("mux") if profile is not None else given.mux
        return tr(f"review.file_after.{mux.original.value}", folder=mux.keep_folder)
    if file is not None and file.writes:
        return tr("review.file_after.in_place")
    return tr("review.file_after.stays")
