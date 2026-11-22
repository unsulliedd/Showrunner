"""The sync step: an engine moves a paired subtitle onto its reference, and the same two checks follow whichever engine
it was. A subtitle already in time with the reference is kept as it is; a result the engine or its score doubts is
marked for review. What the step found is kept beside its result, so a resumed job and the views read it without
running anything.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.tools.sync import IN_SYNC_BELOW, UNSURE_BELOW, SyncAdapter, SyncError, SyncOutcome, SyncRequest

_REPORT = ".sync.json"


@dataclass(frozen=True, slots=True)
class SyncReport:
    """What a sync step found in one subtitle."""

    engine: str
    offset: float  # seconds the engine moved the subtitle by; negative is earlier
    scale: float  # the stretch applied before the offset; 1 is none
    score: float  # the engine's confidence, see `SyncOutcome.score`
    shift: float  # the largest distance any line was moved by
    in_sync: bool  # the subtitle was already in time, so it was kept as it is
    needs_review: bool  # the engine or the score doubts the result


def thresholds(adapter: SyncAdapter, settings: Mapping[str, str]) -> tuple[float, float]:
    """The shift below which a subtitle counts as in sync and the score below which a result needs review: the place's
    values, the engine's own where a place sets none or one that is no number."""
    return (
        _number(settings.get(IN_SYNC_BELOW), float(adapter.defaults[IN_SYNC_BELOW])),
        _number(settings.get(UNSURE_BELOW), float(adapter.defaults[UNSURE_BELOW])),
    )


def judge(adapter: SyncAdapter, outcome: SyncOutcome, settings: Mapping[str, str]) -> SyncReport:
    """The checks on what an engine found, against the thresholds of the place."""
    in_sync_below, unsure_below = thresholds(adapter, settings)
    return SyncReport(
        adapter.name,
        outcome.offset,
        outcome.scale,
        outcome.score,
        outcome.shift,
        in_sync=outcome.shift < in_sync_below,
        needs_review=outcome.unsure or outcome.score < unsure_below,
    )


def sync_runner(adapters: Mapping[str, SyncAdapter]) -> Runner:
    """The runner of the sync step, taking the engine the step names from `adapters`, by name. A subtitle in sync is
    written as a copy of the one it was given, byte for byte, so the step's result always exists."""

    def run(work: StepWork, cancel: threading.Event | None) -> None:
        if work.source is None:
            raise ValueError("syncing needs the subtitle it works on")
        adapter = adapters.get(work.step.engine.value)
        if adapter is None:
            raise SyncError(f"{work.step.engine.value} cannot run")
        if work.reference is None and not adapter.audio:
            raise SyncError(f"{adapter.name} needs a program to work against the audio")
        settings = dict(work.step.settings)
        outcome = adapter.sync(
            SyncRequest(
                work.source,
                work.video,
                work.reference,
                work.output,
                settings,
                work.language,
                progress=work.progress,
                cancel=cancel,
            )
        )
        report = judge(adapter, outcome, settings)
        if report.in_sync:
            shutil.copyfile(work.source, work.output)
        _report_path(work.output).write_text(json.dumps(asdict(report)), encoding="utf-8")

    return run


def read_report(output: Path) -> SyncReport | None:
    """What the sync step that wrote `output` found; None when it has not run or its report is lost."""
    try:
        return SyncReport(**json.loads(_report_path(output).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def _report_path(output: Path) -> Path:
    return output.with_name(output.name + _REPORT)


def _number(text: str | None, default: float) -> float:
    try:
        value = float(text) if text else default
    except ValueError:
        return default
    return value if value >= 0 else default
