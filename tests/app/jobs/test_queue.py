"""The queue's rules over stored jobs: its table in the store, an item's state, Retry, Pause between steps, and what
adding a place does to the items already queued."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.queue import ItemState, can_retry, item_state, next_item, place
from showrunner.app.jobs.run import create_job, run_job
from showrunner.app.jobs.store import JobStore, QueuedJob, QueueMark, StepState
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaItem


def queue(store: JobStore, profile: Profile, stage: object, items: list[MediaItem], name: str = "Season 1") -> int:
    job = create_job(store, preview(items, profile, (stage,)), profile, (stage,))  # type: ignore[arg-type]
    store.enqueue(job, name, [i.file.path for i in items])
    return job


def item(states: tuple[StepState, ...], mark: QueueMark = QueueMark.QUEUED, paths: tuple[str, ...] = ()) -> QueuedJob:
    return QueuedJob(1, "Season 1", tuple(Path(p) for p in paths), mark, "", states)


P, R, D, F, S, K = (StepState.PENDING, StepState.RUNNING, StepState.DONE, StepState.FAILED, StepState.STALE,
                    StepState.SKIPPED)  # fmt: skip


def test_an_item_reads_its_state_from_its_steps_and_mark() -> None:
    assert item_state(item((P, P)), False) is ItemState.WAITING
    assert item_state(item((P, P)), True) is ItemState.RUNNING
    assert item_state(item((D, P)), False) is ItemState.INTERRUPTED
    assert item_state(item((D, R)), False) is ItemState.INTERRUPTED  # running when the app stopped
    assert item_state(item((D, D)), False) is ItemState.DONE
    assert item_state(item((D, F, K)), False) is ItemState.FAILED
    assert item_state(item((S, K, D)), False) is ItemState.CHANGED
    assert item_state(item((D, P), QueueMark.CANCELLED), False) is ItemState.CANCELLED
    assert item_state(item((P,), QueueMark.UNREADABLE), False) is ItemState.UNREADABLE


def test_retry_is_offered_for_a_failure_or_a_cancel_and_not_for_a_changed_file() -> None:
    for states, mark, expected in [
        ((D, F), QueueMark.QUEUED, True),
        ((P,), QueueMark.FAILED, True),
        ((D, P), QueueMark.CANCELLED, True),
        ((S, K), QueueMark.QUEUED, False),
        ((P,), QueueMark.UNREADABLE, False),
        ((D, D), QueueMark.QUEUED, False),
    ]:
        queued = item(states, mark)
        assert can_retry(queued, item_state(queued, False)) is expected, (states, mark)


def test_the_oldest_item_that_can_run_runs_next() -> None:
    done, interrupted, waiting = item((D,)), item((D, P)), item((P,))
    assert next_item([done, interrupted, waiting]) is interrupted
    assert next_item([done, waiting]) is waiting
    assert next_item([done, item((P,), QueueMark.CANCELLED)]) is None


def test_a_place_queued_again_replaces_a_waiting_item_it_holds_whole() -> None:
    season = QueuedJob(1, "Season 1", (Path("e1"), Path("e2")), QueueMark.QUEUED, "", (P, P))
    other = QueuedJob(2, "Season 2", (Path("f1"),), QueueMark.QUEUED, "", (P,))
    assert place([season, other], [Path("e1"), Path("e2")], None).replaces == (season,)
    show = place([season, other], [Path("e1"), Path("e2"), Path("f1")], None)  # the whole show
    assert show.replaces == (season, other)
    assert show.clash is None


def test_a_place_sharing_a_file_with_any_other_unfinished_item_is_refused() -> None:
    season = QueuedJob(1, "Season 1", (Path("e1"), Path("e2")), QueueMark.QUEUED, "", (P, P))
    assert place([season], [Path("e2")], None).clash is season  # an episode of a queued season
    assert place([season], [Path("e1"), Path("e2")], running=1).clash is season
    started = QueuedJob(1, "Season 1", (Path("e1"), Path("e2")), QueueMark.QUEUED, "", (D, P))
    assert place([started], [Path("e1"), Path("e2")], None).clash is started
    finished = QueuedJob(1, "Season 1", (Path("e1"), Path("e2")), QueueMark.QUEUED, "", (D, D))
    assert place([finished], [Path("e2")], None) == place([], [Path("e2")], None)
    assert place([season], [Path("x")], None) == place([], [Path("x")], None)


def test_the_store_keeps_the_queue_and_retry_resets_only_failed_and_skipped_steps(
    files: SimpleNamespace, store: JobStore, profile: Profile, tmp_path: Path
) -> None:
    stage = files.FakeStage()
    first = queue(store, profile, stage, [files.item("a.mkv"), files.item("b.mkv", "fail")])
    second = queue(store, profile, stage, [files.item("c.mkv")], "Season 2")
    reopened = JobStore(tmp_path / "data" / "jobs.sqlite3")
    assert [(q.id, q.name, q.states) for q in reopened.queued()] == [
        (first, "Season 1", (P, P)),
        (second, "Season 2", (P,)),
    ]
    run_job(store, first, (stage,), read=files.read)
    (failed, _) = store.queued()
    assert failed.states == (D, F)
    assert failed.reason == "disk full"
    store.set_mark(first, QueueMark.CANCELLED)
    store.set_state(first, 0, StepState.STALE)
    store.retry(first)
    (retried, _) = store.queued()
    assert retried.states == (S, P)
    assert retried.mark is QueueMark.QUEUED
    store.discard(first)
    assert [q.id for q in store.queued()] == [second]


def test_pause_lets_the_running_step_end_and_the_next_run_goes_on(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    job = queue(store, profile, stage, [files.item("a.mkv"), files.item("b.mkv"), files.item("c.mkv")])
    pause = threading.Event()
    # Pause comes while the first step runs.
    result = run_job(store, job, (stage,), read=files.read, step_changed=lambda _record: pause.set(), pause=pause)
    assert result.paused
    assert not result.cancelled
    assert stage.applied == ["a.mkv"]  # the step that was running when Pause came ended
    assert store.queued()[0].states == (D, P, P)
    result = run_job(store, job, (stage,), read=files.read)
    assert not result.paused
    assert stage.applied == ["a.mkv", "b.mkv", "c.mkv"]
