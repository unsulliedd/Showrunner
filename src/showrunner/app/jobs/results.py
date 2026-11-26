"""The results of slow subtitle work, kept in the data folder so a resumed job reuses what an earlier run made.

Each finished subtitle has a folder named after what it is made of (the video, where it comes from, its language),
and each of its steps a result named after the steps up to it, so a later step's settings changing keeps the earlier
results. Beside each result lies the stamp of every file it was made from: the video, the subtitle it worked on, the
reference. A result is reused only while those stamps hold, so a file changed on disk, or a step before it run again,
runs it again. Folders untouched for `KEEP_DAYS` are removed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from showrunner.app.jobs.hashing import stamp
from showrunner.app.storage.files import write_json_atomic
from showrunner.stages.subtitles import FinishedSubtitle, StepKind, SubtitlePlan
from showrunner.stages.subtitles.sync import SyncReport, read_report
from showrunner.stages.subtitles.translate import TranslateReport
from showrunner.stages.subtitles.translate import read_report as read_translation

KEEP_DAYS = 14
_RECORD = ".json"


@dataclass(frozen=True, slots=True)
class ResultStore:
    root: Path

    def output(self, plan: SubtitlePlan, finished: FinishedSubtitle, index: int) -> Path:
        """Where step `index` of the finished subtitle keeps its result."""
        made_of = (
            str(plan.video),
            finished.source.value,
            finished.language.ietf if finished.language else "",
            str(finished.paired.path) if finished.paired else "",
            finished.track.id if finished.track else None,
        )
        steps = finished.steps[: index + 1]
        # The reference matters to the steps that work against it, so another reference makes another result.
        reference = plan.reference.track.id if plan.reference and plan.reference.track else None
        return self.root / _digest(made_of) / f"{_digest((repr(steps), reference))}.{finished.format}"

    def final(self, plan: SubtitlePlan, finished: FinishedSubtitle) -> Path:
        """The result that goes into the new file: the last step's."""
        return self.output(plan, finished, len(finished.steps) - 1)

    def sync_report(self, plan: SubtitlePlan, finished: FinishedSubtitle) -> SyncReport | None:
        """What the finished subtitle's sync step found, once it has run; None before, or for one with no sync."""
        for index, step in enumerate(finished.steps):
            if step.kind is StepKind.SYNC:
                return read_report(self.output(plan, finished, index))
        return None

    def translate_report(self, plan: SubtitlePlan, finished: FinishedSubtitle) -> TranslateReport | None:
        """What the finished subtitle's translation did, or has done so far while it runs; None before it ran, or for
        one with no translation."""
        for index, step in enumerate(finished.steps):
            if step.kind is StepKind.TRANSLATE:
                return read_translation(self.output(plan, finished, index))
        return None

    def reference(self, plan: SubtitlePlan, rules: str = "") -> Path:
        """Where the file's reference is kept once read, as text. `rules` is the fingerprint of the rules the reading
        applies (the OCR fixes), so a changed rule reads it again."""
        track = plan.reference.track if plan.reference else None
        return self.root / _digest((str(plan.video), track.id if track else None, rules)) / "reference.srt"

    def kept(self, output: Path, inputs: Sequence[Path]) -> bool:
        """Whether `output` is there and was made from `inputs` as they are now."""
        try:
            held = json.loads((output.parent / (output.name + _RECORD)).read_text(encoding="utf-8"))
            current = _stamps(inputs)
        except (OSError, ValueError):
            return False
        if not output.is_file() or held != current:
            return False
        os.utime(output.parent)  # in use, so not pruned
        return True

    def keep(self, output: Path, inputs: Sequence[Path]) -> None:
        """Record what `output`, just written, was made from. Written last, so a result cut short is never reused."""
        write_json_atomic(output.parent / (output.name + _RECORD), _stamps(inputs))

    def prune(self, now: float | None = None) -> None:
        """Remove the folders no run has written or reused for `KEEP_DAYS`."""
        limit = (time.time() if now is None else now) - KEEP_DAYS * 86400
        try:
            folders = [entry for entry in self.root.iterdir() if entry.is_dir()]
        except OSError:
            return
        for folder in folders:
            try:
                if folder.stat().st_mtime < limit:
                    shutil.rmtree(folder)
            except OSError:
                continue  # in use or gone; tried again next time


def _stamps(inputs: Sequence[Path]) -> list[dict[str, object]]:
    return [asdict(stamp(path)) for path in inputs]


def _digest(value: object) -> str:
    return hashlib.blake2b(repr(value).encode("utf-8"), digest_size=10).hexdigest()
