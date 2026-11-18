"""Job progress in SQLite: one row per job and one per step (a stage applied to a file), committed as each step
starts and ends, so a crash loses at most the step that was running."""

from __future__ import annotations

import contextlib
import json
import pickle
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner import __version__
from showrunner.app.jobs.hashing import FileStamp
from showrunner.app.jobs.stages import StagePlan
from showrunner.app.profiles import registered  # noqa: F401  # a stored profile must load with every stage
from showrunner.app.profiles.profile import Profile, profile_from_json, profile_to_json
from showrunner.core.media import MediaItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    created REAL NOT NULL,
    app_version TEXT NOT NULL,
    options_key TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    profile TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    job INTEGER NOT NULL REFERENCES jobs (id),
    position INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    item BLOB NOT NULL,
    plan BLOB NOT NULL,
    state TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (job, position)
);
CREATE TABLE IF NOT EXISTS finished (
    content_hash TEXT NOT NULL,
    options_key TEXT NOT NULL,
    PRIMARY KEY (content_hash, options_key)
);
CREATE TABLE IF NOT EXISTS queue (
    job INTEGER PRIMARY KEY REFERENCES jobs (id),
    name TEXT NOT NULL,
    paths TEXT NOT NULL,
    mark TEXT NOT NULL DEFAULT 'queued',
    message TEXT NOT NULL DEFAULT ''
);
"""


class StepState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"  # started and not ended: after a crash, what it wrote is unknown
    DONE = "done"
    FAILED = "failed"
    STALE = "stale"  # the file changed since the preview; a new preview is needed
    SKIPPED = "skipped"  # an earlier step of the same file did not finish


FINAL = frozenset({StepState.DONE, StepState.FAILED, StepState.STALE, StepState.SKIPPED})


class QueueMark(StrEnum):
    """What a queue item's steps cannot tell: the user cancelled it, or the job could not run as a whole."""

    QUEUED = "queued"
    CANCELLED = "cancelled"
    FAILED = "failed"  # the run stopped on an error outside any step
    UNREADABLE = "unreadable"  # stored by another version, or no longer readable: it can only be removed


@dataclass(frozen=True, slots=True)
class QueuedJob:
    """A queue item as the queue lists it, read without unpickling its steps, so an item a later version cannot
    resume is still listed."""

    id: int
    name: str
    paths: tuple[Path, ...]  # the files the item writes
    mark: QueueMark
    message: str
    states: tuple[StepState, ...]  # of its steps, in order
    reason: str = ""  # the message of its first failed step


class UnresumableJobError(Exception):
    """A stored job can no longer be read, for example after an update changed the shape of its plans."""


@dataclass(frozen=True, slots=True)
class StoredStep:
    position: int
    item: MediaItem
    stamp: FileStamp  # of the file at preview
    plan: StagePlan
    state: StepState
    message: str = ""
    options_key: str = ""  # of the options its file was planned with, a key of `StoredJob.profiles`

    @property
    def path(self) -> Path:
        return self.item.file.path


@dataclass(frozen=True, slots=True)
class StoredJob:
    id: int
    created: float  # seconds since the epoch
    options_key: str
    profiles: dict[str, Profile]  # by options key: each file is planned with its own place's options
    steps: tuple[StoredStep, ...]

    def profile_of(self, step: StoredStep) -> Profile:
        return self.profiles[step.options_key]


@dataclass(frozen=True, slots=True)
class JobSummary:
    id: int
    created: float
    profile_name: str
    steps: int
    finished: int  # steps in a final state


class JobStore:
    """The database file is created on first use. Every call opens its own connection, so the store can be used
    from any thread.

    Items and plans are stored as pickles of the app's own frozen dataclasses, so a job resumes without the
    library loaded. Unpickling runs code, which is acceptable here because the data folder already holds the
    programs the app runs and is trusted like the app itself. A pickle made by another version of the app can
    load with values in the wrong fields, so a job is resumed only by the version that stored it.
    The version is the guard, so `__version__` is raised whenever a stored type changes shape.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # Write-ahead logging keeps a reader from blocking the writer; the setting stays with the file.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path)
        try:
            with connection:  # one transaction, committed on leaving
                yield connection
        finally:
            connection.close()

    def create(
        self,
        options_key: str,
        profiles: Mapping[str, Profile],
        steps: Sequence[tuple[MediaItem, FileStamp, StagePlan, str]],
    ) -> int:
        """Each step is an item, its stamp, its plan and the key in `profiles` of the options it was planned with.
        The options are stored in the job's `profile` column as one object, with each step's key in order."""
        stored = {
            "profiles": {key: profile_to_json(profile) for key, profile in profiles.items()},
            "steps": [key for *_, key in steps],
        }
        name = next(iter(profiles.values())).name if profiles else ""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO jobs (created, app_version, options_key, profile_name, profile) VALUES (?, ?, ?, ?, ?)",
                (time.time(), __version__, options_key, name, json.dumps(stored)),
            )
            job_id = cursor.lastrowid
            assert job_id is not None
            connection.executemany(
                "INSERT INTO steps (job, position, size, mtime_ns, content_hash, item, plan, state)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        job_id,
                        position,
                        stamp.size,
                        stamp.mtime_ns,
                        stamp.content_hash,
                        pickle.dumps(item),
                        pickle.dumps(plan),
                        StepState.PENDING.value,
                    )
                    for position, (item, stamp, plan, _key) in enumerate(steps)
                ],
            )
        return job_id

    def load(self, job_id: int) -> StoredJob:
        """Raises KeyError for an unknown job and `UnresumableJobError` for one that cannot be read back."""
        with self._connect() as connection:
            job = connection.execute(
                "SELECT created, app_version, options_key, profile_name, profile FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            rows = connection.execute(
                "SELECT position, size, mtime_ns, content_hash, item, plan, state, message FROM steps"
                " WHERE job = ? ORDER BY position",
                (job_id,),
            ).fetchall()
        created, version, key, name, profile_text = job
        if version != __version__:
            raise UnresumableJobError(f"job {job_id} was stored by version {version}, this is {__version__}")
        try:
            stored = json.loads(profile_text)
            profiles = {k: profile_from_json(name, data).value for k, data in stored["profiles"].items()}
            keys = stored["steps"]
            steps = tuple(
                StoredStep(
                    position,
                    pickle.loads(item),
                    FileStamp(size, mtime, content),
                    pickle.loads(plan),
                    StepState(state),
                    message,
                    keys[position],
                )
                for position, size, mtime, content, item, plan, state, message in rows
            )
            if any(step.options_key not in profiles for step in steps):
                raise KeyError("a step's options are not stored")
        except Exception as error:  # any failure to rebuild the objects means the job cannot be resumed
            raise UnresumableJobError(f"job {job_id} cannot be read: {error}") from error
        return StoredJob(job_id, created, key, profiles, steps)

    def set_state(self, job_id: int, position: int, state: StepState, message: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE steps SET state = ?, message = ? WHERE job = ? AND position = ?",
                (state.value, message, job_id, position),
            )

    def unfinished(self) -> list[JobSummary]:
        """Jobs with a step that has not reached a final state, oldest first."""
        final = tuple(state.value for state in FINAL)
        marks = ", ".join("?" * len(final))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT jobs.id, jobs.created, jobs.profile_name, COUNT(*),"
                f" SUM(steps.state IN ({marks})) FROM jobs JOIN steps ON steps.job = jobs.id"
                f" GROUP BY jobs.id HAVING SUM(steps.state IN ({marks})) < COUNT(*) ORDER BY jobs.id",
                final + final,
            ).fetchall()
        return [JobSummary(*row) for row in rows]

    def discard(self, job_id: int) -> None:
        """Forget a job, finished or not; for one the user does not want resumed or one that cannot be read."""
        with self._connect() as connection:
            connection.execute("DELETE FROM queue WHERE job = ?", (job_id,))
            connection.execute("DELETE FROM steps WHERE job = ?", (job_id,))
            connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # The queue: stored jobs that run one after another, in the order they were added

    def enqueue(self, job_id: int, name: str, paths: Sequence[Path]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO queue (job, name, paths) VALUES (?, ?, ?)",
                (job_id, name, json.dumps([str(p) for p in paths])),
            )

    def queued(self) -> list[QueuedJob]:
        """Every queue item, oldest first."""
        with self._connect() as connection:
            items = connection.execute("SELECT job, name, paths, mark, message FROM queue ORDER BY job").fetchall()
            steps = connection.execute(
                "SELECT job, state, message FROM steps WHERE job IN (SELECT job FROM queue) ORDER BY job, position"
            ).fetchall()
        states: dict[int, list[StepState]] = {}
        reasons: dict[int, str] = {}
        for job, state, message in steps:
            states.setdefault(job, []).append(StepState(state))
            if state == StepState.FAILED and job not in reasons:
                reasons[job] = message
        return [
            QueuedJob(
                job,
                name,
                tuple(Path(p) for p in json.loads(paths)),
                QueueMark(mark),
                message,
                tuple(states.get(job, ())),
                reasons.get(job, ""),
            )
            for job, name, paths, mark, message in items
        ]

    def set_mark(self, job_id: int, mark: QueueMark, message: str = "") -> None:
        with self._connect() as connection:
            connection.execute("UPDATE queue SET mark = ?, message = ? WHERE job = ?", (mark.value, message, job_id))

    def retry(self, job_id: int) -> None:
        """Make a queue item's failed steps, and those skipped after them, wait again, and clear its mark. A step that
        was running keeps its state, so the run settles what it wrote first; a step that found its file changed stays
        stale, since its plan no longer fits the file."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE steps SET state = ?, message = '' WHERE job = ? AND state IN (?, ?)",
                (StepState.PENDING.value, job_id, StepState.FAILED.value, StepState.SKIPPED.value),
            )
            connection.execute(
                "UPDATE queue SET mark = ?, message = '' WHERE job = ?", (QueueMark.QUEUED.value, job_id)
            )

    def mark_finished(self, content_hash: str, options_key: str) -> None:
        """Remember a file's content after its last step, so a renamed or moved copy is recognized as done."""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO finished (content_hash, options_key) VALUES (?, ?)", (content_hash, options_key)
            )

    def is_finished(self, content_hash: str, options_key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM finished WHERE content_hash = ? AND options_key = ?", (content_hash, options_key)
            ).fetchone()
        return row is not None
