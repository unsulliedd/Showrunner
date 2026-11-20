"""Carrying out a mux plan without ever putting the original at risk.

The order is fixed: write the new file under a partial name beside the original, read it back and check it
against the plan, move the original away (Recycle Bin or keep folder), give the new file its final name, then
move the added subtitle files away. Until the check passes the original is not touched; from then on it is in the
Recycle Bin or the keep folder, never deleted. Every point between two steps can be found again from the files on
disk, which `resume_mux` does after a crash.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.encoding import detect_encoding
from showrunner.core.media import MediaFile
from showrunner.core.track import Track, TrackFlags
from showrunner.stages.mux.options import Original
from showrunner.stages.mux.plan import MuxPlan, MuxTrack
from showrunner.stages.scan.extensions import TEXT_SUBTITLE_EXTENSIONS
from showrunner.tools.mkvtoolnix.merge import Merge, MergeError, OutputTrack, iconv_name, merge
from showrunner.tools.probe import ProbeError, Programs, probe
from showrunner.tools.process import ProcessCancelledError, ProcessError
from showrunner.tools.recycle import recycle as shell_recycle

# How far the new file's duration may be from the original's. An added subtitle can end after the video and a
# dropped track can be longer than the rest, so a small difference is normal; a whole second is not.
DURATION_TOLERANCE_SECONDS = 1.0

Recycle = Callable[[Sequence[Path]], None]
# Called with the name of each step before it runs; tests use it to stop the run between two steps.
Checkpoint = Callable[[str], None]


class Failure(StrEnum):
    OUTPUT_EXISTS = "output-exists"  # detail: the file name
    MERGE = "merge"  # detail: what mkvmerge reported
    VERIFY = "verify"  # see `problems`
    DISPOSE = "dispose"  # the original could not be moved away; detail: why
    RENAME = "rename"  # the new file could not take its name; detail: why
    STALE = "stale"  # after a crash, the files on disk match no point of the run


@dataclass(frozen=True, slots=True)
class VerifyProblem:
    """One way the new file differs from the plan. `position` counts the tracks of the new file from 0, -1 for
    the file itself."""

    what: str  # read, tracks, kind, codec, channels, language, name, flags, title, duration, chapters or attachments
    position: int = -1
    planned: str = ""
    found: str = ""


@dataclass(frozen=True, slots=True)
class MuxResult:
    output: Path | None = None  # the new file under its final name, once it has it
    failure: Failure | None = None
    detail: str = ""
    problems: tuple[VerifyProblem, ...] = ()
    warnings: tuple[str, ...] = ()  # what mkvmerge warned about
    recycled: tuple[Path, ...] = ()  # files that went to the Recycle Bin
    kept: tuple[Path, ...] = ()  # where the files moved to the keep folder are now
    # Added subtitle files that stay beside the video: changed while the remux ran, or could not be moved.
    left: tuple[Path, ...] = ()
    taken: tuple[Path, ...] = ()  # added subtitle files moved away, by the paths they had beside the video
    resumed: bool = False  # finished after an interruption

    @property
    def ok(self) -> bool:
        return self.failure is None


def apply_mux(
    plan: MuxPlan,
    mkvmerge: Path,
    programs: Programs,
    *,
    recycle: Recycle = shell_recycle,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
    checkpoint: Checkpoint | None = None,
) -> MuxResult:
    """Write, check and swap in the new file. Cancellation propagates as `ProcessCancelledError`, after the
    partial file is removed and with the original untouched."""
    step = checkpoint or (lambda _name: None)
    partial = plan.partial
    if plan.output != plan.source and plan.output.exists():
        return MuxResult(failure=Failure.OUTPUT_EXISTS, detail=plan.output.name)
    partial.unlink(missing_ok=True)  # left by an earlier run of this step
    added = [subtitle.path for subtitle in plan.added]
    before = {path: _signature(path) for path in added}
    try:
        step("merge")
        merged = merge(mkvmerge, _merge_spec(plan, partial), progress=progress, cancel=cancel)
        step("verify")
        problems = check(plan, partial, programs, cancel=cancel)
    except MergeError as error:
        partial.unlink(missing_ok=True)
        return MuxResult(failure=Failure.MERGE, detail=str(error))
    except ProcessCancelledError:
        partial.unlink(missing_ok=True)
        raise
    if problems:
        partial.unlink(missing_ok=True)
        return MuxResult(failure=Failure.VERIFY, problems=problems, warnings=merged.warnings)
    # A subtitle file that changed while mkvmerge read it is not the one in the new file, so it stays.
    unchanged = [path for path in added if before[path] is not None and _signature(path) == before[path]]
    return replace(_finish(plan, partial, recycle, step, unchanged, move_source=True), warnings=merged.warnings)


def resume_mux(
    plan: MuxPlan,
    programs: Programs,
    *,
    source_unchanged: bool,
    recycle: Recycle = shell_recycle,
    cancel: threading.Event | None = None,
) -> MuxResult | None:
    """Settle a run that stopped part way, from the files on disk. None means the original is as it was planned
    and the step runs again; a result says it was finished now or cannot be told apart from a changed file.

    `source_unchanged`: the file at the source path is the one that was planned, by its stamp.
    """
    partial = plan.partial
    added = [subtitle.path for subtitle in plan.added]
    if plan.source.exists() and partial.exists():
        # The original is moved away only after the check, and the partial file is renamed right after that, so
        # with both present the swap had not begun and the partial file is of no use.
        partial.unlink()
    if source_unchanged:
        return None
    if partial.exists():
        # The original was moved away after the partial file passed its check: check again and finish.
        if problems := check(plan, partial, programs, cancel=cancel):
            return MuxResult(failure=Failure.VERIFY, problems=problems, resumed=True)
        return replace(_finish(plan, partial, recycle, None, added, move_source=False), resumed=True)
    if plan.output.exists() and not check(plan, plan.output, programs, cancel=cancel):
        present = [path for path in added if path.exists()]
        recycled, kept, left = _move_away(plan, present, recycle)
        taken = tuple(path for path in added if path not in left)
        return MuxResult(plan.output, recycled=recycled, kept=kept, left=left, taken=taken, resumed=True)
    return MuxResult(failure=Failure.STALE, resumed=True)


def check(
    plan: MuxPlan, path: Path, programs: Programs, *, cancel: threading.Event | None = None
) -> tuple[VerifyProblem, ...]:
    """Read the file and compare it with the plan: the tracks in order with their kind, codec, language, name and
    flags (and channels when the plan puts them in a new order), the title, and the duration within
    `DURATION_TOLERANCE_SECONDS` of the original's."""
    try:
        after = probe(path, programs, cancel=cancel)
    except ProcessCancelledError:
        raise
    except (ProbeError, OSError, ProcessError) as error:
        return (VerifyProblem("read", found=str(error)),)
    if not after.ids_from_mkvmerge:
        return (VerifyProblem("read", found="mkvmerge"),)
    return verify(plan, after)


def verify(plan: MuxPlan, after: MediaFile) -> tuple[VerifyProblem, ...]:
    """Track IDs are numbered again in the new file, so tracks are compared by position."""
    problems: list[VerifyProblem] = []
    if len(after.tracks) != len(plan.tracks):
        return (VerifyProblem("tracks", planned=str(len(plan.tracks)), found=str(len(after.tracks))),)
    for position, (want, got) in enumerate(zip(plan.tracks, after.tracks, strict=True)):
        source = want.planned.track
        pairs = [
            ("kind", source.kind.value, got.kind.value),
            ("language", want.language.ietf if want.language else "", got.language.ietf if got.language else ""),
            ("name", want.name, got.name),
            ("flags", _flags(want.flags), _flags(got.flags)),
        ]
        # A track copied from the video keeps its codec; a subtitle file's codec is mkvmerge's to choose.
        if want.planned.external is None:
            pairs.append(("codec", source.codec, got.codec))
            # In a new order the channels also tell apart two audio tracks that differ in nothing else. Only then:
            # mkvmerge reads the channels again from some audio streams, so a remux that keeps the order is not
            # held to them.
            if plan.reordered:
                pairs.append(("channels", _channels(source), _channels(got)))
        problems += [VerifyProblem(what, position, a, b) for what, a, b in pairs if a != b]
    if after.title != plan.title:
        problems.append(VerifyProblem("title", planned=plan.title, found=after.title))
    for what, planned_count, found_count in (
        ("chapters", plan.chapters, len(after.chapters)),
        ("attachments", plan.attachments, len(after.attachments)),
    ):
        if found_count != planned_count:
            problems.append(VerifyProblem(what, planned=str(planned_count), found=str(found_count)))
    planned = plan.duration
    if planned is not None and (after.duration is None or abs(after.duration - planned) > DURATION_TOLERANCE_SECONDS):
        found = "" if after.duration is None else f"{after.duration:.3f}"
        problems.append(VerifyProblem("duration", planned=f"{planned:.3f}", found=found))
    return tuple(problems)


def _merge_spec(plan: MuxPlan, output: Path) -> Merge:
    added = [subtitle.path for subtitle in plan.added]
    tracks = []
    for track in plan.tracks:
        external = track.planned.external
        if external is None:
            source, track_id, charset = 0, track.planned.track.id, ""
        else:
            source, track_id, charset = added.index(external.path) + 1, 0, _charset(external.path, track)
        tracks.append(
            OutputTrack(source, track_id, track.planned.track.kind, track.name, track.language, track.flags, charset)
        )
    return Merge(output, (plan.source, *added), tuple(tracks), plan.title)


def _charset(path: Path, track: MuxTrack) -> str:
    """The encoding of a text subtitle file, so mkvmerge converts it to UTF-8 rightly; empty for a picture format."""
    if path.suffix.casefold() not in TEXT_SUBTITLE_EXTENSIONS:
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""  # mkvmerge reports the file it cannot read
    codec = detect_encoding(raw, track.language)
    # mkvmerge reads a byte order mark itself.
    return "UTF-8" if codec in {"utf-8", "utf-8-sig"} else iconv_name(codec)


def _finish(
    plan: MuxPlan,
    partial: Path,
    recycle: Recycle,
    checkpoint: Checkpoint | None,
    subtitles: list[Path],
    *,
    move_source: bool,
) -> MuxResult:
    step = checkpoint or (lambda _name: None)
    step("original")
    try:
        moved = _move_away(plan, [plan.source], recycle, strict=True) if move_source else ((), (), ())
    except OSError as error:
        # The shell can report a failure after it moved the file; the checked new file is then the only copy left
        # in place, so it stays for resume to finish.
        if plan.source.exists():
            partial.unlink(missing_ok=True)
        return MuxResult(failure=Failure.DISPOSE, detail=str(error))
    step("rename")
    try:
        partial.rename(plan.output)  # refuses to replace a file on Windows
    except OSError as error:
        return MuxResult(failure=Failure.RENAME, detail=str(error), recycled=moved[0], kept=moved[1])
    step("subtitles")
    added = [subtitle.path for subtitle in plan.added]
    still = [path for path in added if path.exists()]
    gone = _move_away(plan, [path for path in still if path in subtitles], recycle)
    left = tuple(path for path in still if path not in subtitles) + gone[2]
    taken = tuple(path for path in added if path not in left)
    return MuxResult(plan.output, recycled=moved[0] + gone[0], kept=moved[1] + gone[1], left=left, taken=taken)


def _move_away(
    plan: MuxPlan, paths: list[Path], recycle: Recycle, *, strict: bool = False
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    """Recycle or keep the files: (recycled, kept at, left in place). With `strict` a failure raises `OSError`
    and nothing was moved; otherwise a file that cannot be moved is left in place."""
    if not paths:
        return (), (), ()
    if plan.original is Original.RECYCLE:
        try:
            recycle(paths)
        except OSError:
            if strict:
                raise
            return (), (), tuple(paths)
        return tuple(paths), (), ()
    kept, left = [], []
    for path in paths:
        try:
            kept.append(_keep(path, plan.keep_dir))
        except OSError:
            if strict:
                raise
            left.append(path)
    return (), tuple(kept), tuple(left)


def _keep(path: Path, folder: Path) -> Path:
    """Move the file into the folder under its own name, numbered when the folder already holds that name."""
    folder.mkdir(exist_ok=True)
    target, number = folder / path.name, 1
    while target.exists():
        number += 1
        target = folder / f"{path.stem} ({number}){path.suffix}"
    path.rename(target)
    return target


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


def _channels(track: Track) -> str:
    return str(track.audio.channels) if track.audio is not None and track.audio.channels is not None else ""


def _flags(flags: TrackFlags) -> str:
    names = ("default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original")
    return ",".join(name for name in names if getattr(flags, name))
