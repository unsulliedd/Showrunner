"""The queue's rules over stored jobs: what state an item is in, which runs next, and what adding a place does to the
items already there. Running an item is running its job, as Apply does."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner.app.jobs.store import FINAL, QueuedJob, QueueMark, StepState


class ItemState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    INTERRUPTED = "interrupted"  # stopped part way by Pause or by the app closing; the next run goes on from there
    DONE = "done"
    FAILED = "failed"
    CHANGED = "changed"  # a file changed on disk after it was queued, so its planned changes were not written
    CANCELLED = "cancelled"
    UNREADABLE = "unreadable"


def item_state(item: QueuedJob, running: bool) -> ItemState:
    if running:
        return ItemState.RUNNING
    if item.mark is QueueMark.UNREADABLE:
        return ItemState.UNREADABLE
    if item.mark is QueueMark.CANCELLED:
        return ItemState.CANCELLED
    if item.mark is QueueMark.FAILED:
        return ItemState.FAILED
    if all(state in FINAL for state in item.states):
        if StepState.FAILED in item.states:
            return ItemState.FAILED
        if StepState.STALE in item.states:
            return ItemState.CHANGED
        return ItemState.DONE
    if all(state is StepState.PENDING for state in item.states):
        return ItemState.WAITING
    return ItemState.INTERRUPTED


RUNNABLE = frozenset({ItemState.WAITING, ItemState.INTERRUPTED})
# An item in one of these still holds its files: adding one of them again would plan from a file it may yet change.
UNFINISHED = RUNNABLE | {ItemState.RUNNING, ItemState.FAILED, ItemState.CANCELLED}


def can_retry(item: QueuedJob, state: ItemState) -> bool:
    """Retry runs the failed steps again with the plans kept when the item was added; an item whose only problem is a
    changed file gets none, since those plans no longer fit it."""
    return state is ItemState.CANCELLED or (state is ItemState.FAILED and item.mark is not QueueMark.UNREADABLE)


def next_item(items: Sequence[QueuedJob]) -> QueuedJob | None:
    """The oldest item that can run."""
    return next((i for i in items if item_state(i, False) in RUNNABLE), None)


@dataclass(frozen=True, slots=True)
class Placement:
    """What adding a place with these files does: the waiting items it takes the place of, or the item it clashes
    with, which refuses the add."""

    replaces: tuple[QueuedJob, ...] = ()
    clash: QueuedJob | None = None


def place(items: Sequence[QueuedJob], paths: Collection[Path], running: int | None) -> Placement:
    """A file can be in one unfinished item only. A waiting item whose files the new one all holds is replaced by
    it, so queuing a place again after changing its settings queues it with the new ones; any other unfinished item
    that shares a file refuses the add, since it may change the file before the new one runs."""
    new = set(paths)
    replaces = []
    for item in items:
        state = item_state(item, item.id == running)
        if state not in UNFINISHED or new.isdisjoint(item.paths):
            continue
        if state is ItemState.WAITING and new.issuperset(item.paths):
            replaces.append(item)
        else:
            return Placement(clash=item)
    return Placement(tuple(replaces))
