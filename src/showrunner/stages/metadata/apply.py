"""Applying a metadata plan: edit the headers, read the file again and check every change landed."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from showrunner.core.media import MediaFile
from showrunner.core.track import Track
from showrunner.stages.metadata.plan import FLAG_FIELDS, HeaderChange, MetadataPlan
from showrunner.tools.mkvtoolnix.propedit import PropeditError, Property, edit_headers
from showrunner.tools.probe import ProbeError, Programs, probe
from showrunner.tools.process import ProcessTimeoutError, ProgramNotFoundError

DEFAULT_TIMEOUT_SECONDS = 60.0

# Reading the file again can fail without the edit being wrong; cancellation is not caught here.
_READ_ERRORS = (ProbeError, OSError, ProcessTimeoutError, ProgramNotFoundError)


@dataclass(frozen=True, slots=True)
class ApplyResult:
    landed: tuple[HeaderChange, ...] = ()
    # Changes the file read afterwards does not show, or every change when it could not be read.
    missed: tuple[HeaderChange, ...] = ()
    error: str = ""  # what mkvpropedit or the second read reported

    @property
    def ok(self) -> bool:
        return not self.missed and not self.error


def apply_metadata(
    plan: MetadataPlan,
    mkvpropedit: Path,
    programs: Programs,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    cancel: threading.Event | None = None,
) -> ApplyResult:
    """Run the plan's edits in the file, then read the file again and report what did not change.

    A plan without changes, or one that a remux carries out, runs nothing.
    """
    if not plan.changes or plan.needs_remux:
        return ApplyResult()
    error = ""
    try:
        edit_headers(mkvpropedit, plan.path, [change.edit for change in plan.changes], timeout=timeout, cancel=cancel)
    except PropeditError as failure:
        error = str(failure)
    # Read even after a failure: the program may have written part of the edits before it stopped.
    try:
        after = probe(plan.path, programs, timeout=timeout, cancel=cancel)
    except _READ_ERRORS as failure:
        return ApplyResult((), plan.changes, error or str(failure))
    if not after.ids_from_mkvmerge:
        return ApplyResult((), plan.changes, error or "read without mkvmerge, so track IDs cannot be checked")
    landed = tuple(change for change in plan.changes if _landed(change, after))
    return ApplyResult(landed, tuple(c for c in plan.changes if c not in landed), error)


def _landed(change: HeaderChange, after: MediaFile) -> bool:
    if change.prop is Property.TITLE:
        return after.title == change.new
    track = next((t for t in after.tracks if t.id == change.track_id), None)
    return track is not None and _value(change.prop, track) == change.new


def _value(prop: Property, track: Track) -> str | bool:
    if prop is Property.NAME:
        return track.name
    if prop is Property.LANGUAGE:
        return track.language.ietf if track.language else ""
    return getattr(track.flags, FLAG_FIELDS[prop])
