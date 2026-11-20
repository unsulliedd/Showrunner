from __future__ import annotations

from showrunner.ui.quick.facts import size_text


def test_sizes_read_short() -> None:
    assert size_text(214_000) == "214 KB"
    assert size_text(6_840_000_000) == "6.84 GB"
    assert size_text(12) == "12 B"
