"""Python's garbage collection, moved onto the GUI thread.

The collector runs on whichever thread allocates enough to pass its threshold, a thread-pool thread included. A
collection there, while the GUI thread was inside Qt, crashed the process with an access violation, even with nothing
of Qt's being freed. So automatic collection is switched off and a timer on the GUI thread collects instead, by the
collector's own thresholds.
"""

from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 50


def due(count: tuple[int, int, int], threshold: tuple[int, int, int]) -> int | None:
    """The generation the collector would collect for these counts, or None. A third threshold of 0 means the oldest
    generation is collected in increments by the middle one's collections, as from Python 3.14."""
    young, middle, old = count
    first, second, third = threshold
    if young <= first:
        return None
    if third and old > third:
        return 2
    return 1 if middle > second else 0


def collect_on_gui_thread(parent: QObject) -> QTimer:
    """Switch automatic collection off and collect from a timer owned by `parent`, which lives on the GUI thread."""

    def collect() -> None:
        generation = due(gc.get_count(), gc.get_threshold())
        if generation is not None:
            gc.collect(generation)

    gc.disable()
    timer = QTimer(parent)
    timer.setInterval(INTERVAL_MS)
    timer.timeout.connect(collect)
    timer.start()
    return timer
