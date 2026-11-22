"""What the Review place draws, as plain lists and dicts for QML: the run's changes grouped by kind, each kind ticked
or not for this run, and one card per file with what changes in it.

Two plans come in. `run` is planned with the unticked kinds emptied, as Apply will run it; `full` with every kind in,
so an unticked kind can still show what it would do. Files out of the run are in both plans and only out of the counts
here and of the job (`create_job(left_out_files=...)`): the excluded ones, saved with the workspace, and the unticked
ones, skipped this time only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import Path

from showrunner.app.batches.batch import Media
from showrunner.app.jobs.blocked import StageBlock, blocked_stages
from showrunner.app.jobs.counts import file_parts, ruled_flags
from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaItem
from showrunner.core.track import Track, TrackFlags, TrackKind
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.metadata.plan import FLAG_FIELDS
from showrunner.stages.mux.options import MuxOptions
from showrunner.stages.subtitles import FinishedSubtitle, StepKind, SubtitlePlan
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
    ChangeGroup.NAMES: ("titles", "names", "languages", "implied"),
    ChangeGroup.SUBTITLES: ("subtitles", "subtitle_file"),
}
GROUP_ICONS = {ChangeGroup.TRACKS: "audio", ChangeGroup.NAMES: "names", ChangeGroup.SUBTITLES: "subs"}
_SINGLE = ("new_file", "order", "subtitle_file")  # kinds of change a file has at most one of
FILTERS = ("all", "look")
# A file's state in Review: in the run, in it but needing a look, unticked (skipped this time), or excluded.
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
    unsure: Set[Path] = frozenset()  # the scan found more than one subtitle file that fits
    # By group, how many places inside the open place hold a tick of their own that is not the open place's.
    held_inside: Mapping[ChangeGroup, int] = field(default_factory=dict)


def parts(file: FilePreview | None) -> dict[str, int]:
    """A file's changes by kind: the new file, its track order and the flags the rules move (Tracks and new files),
    then titles, track names, languages and the flags a name implies (Names and flags), then the finished
    subtitles and the new file only they ask for (Subtitles). They add up to `count_changes`."""
    if file is None:
        return dict.fromkeys((key for keys in LINES.values() for key in keys), 0)
    return dict(file_parts(file))


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


def skipped(given: ReviewInput, written: int) -> int:
    """The planned changes this run leaves out with its unticked kinds and files; they stay planned. `written` is
    what Apply writes, the first of `totals`."""
    if not given.run:
        return 0
    full = _by_path(given.full)
    planned = sum(
        sum(parts(f).values())
        for i in given.items
        if i.file.path not in given.excluded and (f := full.get(i.file.path)) is not None and f.writes
    )
    return max(planned - written, 0)


def review(given: ReviewInput) -> dict[str, object]:
    run, full = _by_path(given.run), _by_path(given.full)
    included, writing = _writing(given, run)
    run_parts = {i.file.path: parts(run.get(i.file.path)) for i in given.items}
    full_parts = {i.file.path: parts(full.get(i.file.path)) for i in given.items}
    changes, files = totals(given)
    run_view = BatchView.build(given.items, given.tracks, given.run, given.failures)
    full_view = BatchView.build(given.items, given.tracks, given.full, given.failures)
    shown = _shown_groups(given, full_parts)
    rows = [_row(given, item, run_view, full_view, run_parts[item.file.path], shown) for item in given.items]
    counts = {"all": len(rows), "look": sum(r["state"] == "look" for r in rows)}
    stays = ([tr("review.stays.file_names")] if not given.mux.suffix else []) + [tr(f"review.stays.{k}") for k in STAYS]
    if ChangeGroup.SUBTITLES not in shown:
        stays.insert(0, tr("review.stays.subtitles"))
    return {
        "count": changes,
        "files": files,
        "title": _changes_in(changes, files) if changes else tr("review.nothing"),
        "groups": [_group(given, group, included, writing, run_parts, full_parts) for group in shown],
        "stays": stays,
        "filters": [{"key": key, "label": tr(f"review.filter.{key}"), "count": counts[key]} for key in FILTERS],
        "rows": _with_seasons(given.items, [r for r in rows if _shown(given.filter, str(r["state"]))]),
        "apply_text": _apply_text(given, full_parts, changes, files) if changes else tr("review.apply_none"),
    }


def missing_phases(finished: FinishedSubtitle) -> list[str]:
    """The Jobs phases of the work a left-out subtitle misses, its own steps first: "sync" says more than the reading
    of the reference it also needs. A reading that is not one of its steps is the reference's."""
    own = {step.kind for step in finished.steps}
    phases = [kind.value for kind in finished.missing if kind in own]
    phases += ["reference" if kind is StepKind.READ else kind.value for kind in finished.missing if kind not in own]
    return phases


def left_out(files: Sequence[FilePreview]) -> dict[str, int]:
    """How many finished subtitles the files' plans leave out for work this version cannot do, by the main phase each
    misses."""
    return dict(
        Counter(
            missing_phases(finished)[0]
            for file in files
            if (stage := file.plan_for("subtitles")) is not None and isinstance(stage.plan, SubtitlePlan)
            for finished in stage.plan.left_out
        )
    )


def unavailable_text(phase: str, count: int) -> str:
    """ "Sync is not available in this version yet, so 9 subtitles are left out." """
    return tr_plural("review.subtitles.unavailable", count, step=tr(f"jobs.phase.{phase}"))


def _shown_groups(given: ReviewInput, full_parts: dict[Path, dict[str, int]]) -> list[ChangeGroup]:
    """The groups Review shows a card for: Subtitles only where it plans work, is unticked or is set otherwise in a
    place inside, since a batch without subtitle settings has it under "Stays as it is" instead."""
    work = any(_group_count(full_parts[i.file.path], ChangeGroup.SUBTITLES) for i in given.items)
    held = given.held_inside.get(ChangeGroup.SUBTITLES, 0)
    keep = work or held or ChangeGroup.SUBTITLES in given.groups_out or bool(left_out(given.full))
    return [group for group in ChangeGroup if keep or group is not ChangeGroup.SUBTITLES]


def _with_seasons(items: Sequence[MediaItem], rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Each row with `season`: the season's divider above the first row of each run of its episodes, empty elsewhere
    and where the batch holds one season or none."""
    seasons = {str(i.file.path): i.identity.season for i in items if isinstance(i.identity, Episode)}
    many = len({(i.identity.show, i.identity.season) for i in items if isinstance(i.identity, Episode)}) > 1
    last: int | None = None
    marked = []
    for row in rows:
        season = seasons.get(str(row["path"]))
        divider = many and season is not None and season != last
        marked.append({**row, "season": tr("library.season", number=season) if divider else ""})
        last = season
    return marked


def _apply_text(given: ReviewInput, full_parts: dict[Path, dict[str, int]], changes: int, files: int) -> str:
    """ "Apply 2 of 3 kinds to 33 files": the kinds that plan a change anywhere, and those of them still ticked."""
    planned = [
        group
        for group in ChangeGroup
        if any(_group_count(full_parts[i.file.path], group) for i in given.items if i.file.path not in given.excluded)
    ]
    ticked = sum(group not in given.groups_out for group in planned)
    return tr_plural("review.apply", len(planned), ticked=ticked, files=tr_plural("top.files", files))


def _changes_in(changes: int, files: int) -> str:
    return tr("top.changes_in", changes=tr_plural("top.changes", changes), files=tr_plural("top.files", files))


def _shown(which: str, state: str) -> bool:
    return which in ("all", state)


def _group(
    given: ReviewInput,
    group: ChangeGroup,
    included: Sequence[MediaItem],
    writing: Sequence[MediaItem],
    run_parts: dict[Path, dict[str, int]],
    full_parts: dict[Path, dict[str, int]],
) -> dict[str, object]:
    """A kind's card: ticked, its lines count the run plan; unticked they count what it would do, struck. Its box
    says how many files it changes."""
    out = group in given.groups_out
    source, files = (full_parts, included) if out else (run_parts, writing)
    lines = [
        {"label": tr(f"review.line.{key}"), "count": count}
        for key in LINES[group]
        if (count := sum(source[i.file.path][key] for i in files))
    ]
    changed = sum(_group_count(source[i.file.path], group) > 0 for i in files)
    title = tr(f"review.group.{group.value}")
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
        "title": title,
        "label": tr("review.group_files", title=title, files=tr_plural("top.files", changed)) if changed else title,
        "in_run": not out,
        # Marked as the views mark where a value comes from: places inside set this box otherwise.
        "mark": {"from": "", "over": tr_plural("review.held_inside", held)}
        if (held := given.held_inside.get(group, 0))
        else {},
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
    if group is ChangeGroup.SUBTITLES:
        found += [unavailable_text(phase, count) for phase, count in left_out(given.full).items()]
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
    elif group is ChangeGroup.NAMES:
        found += blocked_lines(blocks.get("metadata"))
    return found


# File cards


def _row(
    given: ReviewInput,
    item: MediaItem,
    run_view: BatchView,
    full_view: BatchView,
    found: dict[str, int],
    groups: Sequence[ChangeGroup],
) -> dict[str, object]:
    path = item.file.path
    run_file, full_file = run_view.file(item), full_view.file(item)
    warning = (
        run_view.failure(item)
        or (run_view.warning(item) if run_file is not None else "")
        or (tr("library.tip.unsure") if path in given.unsure else "")
    )
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
    if count:
        summary = _summary(found)
    elif state != "excluded" and (planned := sum(every.values())):
        summary = tr_plural("top.skipped", planned)
    else:
        summary = tr("review.file.nothing" if run_view.was_read(item) else "tracks.not_read")
    return {
        "path": str(path),
        "number": item_number(item),
        "title": item_title(item),
        "state": state,
        "count": count,
        "summary": summary,
        "warning": warning,
        # One mark per group: amber where the group changes this file in the run, faint where it would but is out.
        "marks": [
            {
                "key": group.value,
                "on": _group_count(found, group) > 0 and state not in OUT_STATES,
                "out": _group_count(every, group) > 0 and (group in given.groups_out or state in OUT_STATES),
            }
            for group in groups
        ],
        "detail": _detail(given, item, run_file, full_file),
    }


def _summary(found: dict[str, int]) -> str:
    """ "3 changes · new file, 2 flags"."""
    what = [
        tr(f"review.part.{key}") if key in _SINGLE else tr_plural(f"review.part.{key}", n)
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
    # Video stays out: "no video" would read as a file without one, and the video line's pill shows its D already.
    for kind in (TrackKind.AUDIO, TrackKind.SUBTITLE):
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
    renamed = new_names(named)
    if renamed:
        tracks = {t.id: t for t in item.file.tracks}
        before_names = [tracks[i].name for i in renamed if i in tracks]
        rows.append(_line("names", _joined(before_names), _joined(list(renamed.values())), names_out))
    rows += _edits(item, full_file if tracks_out else run_file, named, renamed, tracks_out, names_out)
    return rows


def _edits(
    item: MediaItem,
    tracks_file: FilePreview | None,
    named: FilePreview | None,
    renamed: dict[int, str],
    tracks_out: bool,
    names_out: bool,
) -> list[dict[str, object]]:
    """One sentence per flag or language a plan changes, by track: the flags the track rules move, then what
    Metadata writes (the flags a name implies, languages). The pills show a track by its language and its default and
    forced marks only, so these say what the rows cannot."""
    stage = tracks_file.plan_for("tracks") if tracks_file is not None else None
    plan = stage.plan if stage is not None and isinstance(stage.plan, TrackPlan) else None
    found: list[tuple[str, str, bool]] = []  # kind, sentence, left out
    for kept in plan.kept if plan is not None else ():
        for change in kept.flag_changes:
            found.append(("flag", _flag_sentence(change.flag.value, change.value, kept.track, ""), tracks_out))
    stage = named.plan_for("metadata") if named is not None else None
    if stage is not None and isinstance(stage.plan, MetadataPlan):
        own = named.plan_for("tracks") if named is not None else None
        ruled = ruled_flags(own.plan if own is not None and isinstance(own.plan, TrackPlan) else None)
        tracks = {t.id: t for t in item.file.tracks}
        for change in stage.plan.changes:
            track = tracks.get(change.track_id) if change.track_id is not None else None
            if track is None:
                continue
            name = renamed.get(track.id, "")
            if change.prop in FLAG_FIELDS and (change.prop, track.id) not in ruled:
                sentence = _flag_sentence(FLAG_FIELDS[change.prop], bool(change.new), track, name)
                found.append(("flag", sentence, names_out))
            elif change.prop is Property.LANGUAGE:
                language = Language.parse(str(change.new)) if change.new else None
                sentence = tr(
                    "review.edit.language",
                    language=language.name if language is not None else tr("tracks.no_language"),
                    track=_track_label(track, name),
                )
                found.append(("language", sentence, names_out))
    shown: set[str] = set()
    rows = []
    for kind, sentence, out in found:
        label = "" if kind in shown else tr(f"review.detail.{kind}")
        shown.add(kind)
        rows.append({**_line("file", "", "", out), "label": label, "text": sentence})
    return rows


def _flag_sentence(flag: str, on: bool, track: Track, name: str) -> str:
    return tr(
        "review.edit.flag_on" if on else "review.edit.flag_off",
        flag=tr(f"review.flag.{flag}"),
        track=_track_label(track, name),
    )


def _track_label(track: Track, name: str) -> str:
    """The name the track has, else the one it gets; without either, "English audio"."""
    language = track.language.ietf if track.language else NO_LANGUAGE
    return track.name or name or language_kind(language, track.kind)


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
        "text": "",  # a sentence in place of before and after
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
