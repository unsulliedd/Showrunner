"""Garbage collection follows the collector's own thresholds, from a timer on the GUI thread."""

from __future__ import annotations

import pytest

from showrunner.ui.quick.collector import due


@pytest.mark.parametrize(
    ("count", "threshold", "generation"),
    [
        ((2000, 10, 0), (2000, 10, 0), None),
        ((2001, 3, 0), (2000, 10, 0), 0),
        ((2001, 11, 0), (2000, 10, 0), 1),
        ((2001, 11, 50), (2000, 10, 0), 1),
        ((701, 11, 11), (700, 10, 10), 2),
        ((701, 3, 11), (700, 10, 10), 2),
        ((701, 11, 10), (700, 10, 10), 1),
    ],
)
def test_the_generation_due_matches_the_thresholds(
    count: tuple[int, int, int], threshold: tuple[int, int, int], generation: int | None
) -> None:
    assert due(count, threshold) == generation
