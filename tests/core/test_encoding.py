# ruff: noqa: RUF001 (Turkish letters are the point of this data)
from __future__ import annotations

from showrunner.core.encoding import decode_text
from showrunner.core.language import Language

TURKISH = "Çocuklar şimdi okuldan döndü, yarın erken kalkıp İstanbul'a gideceğiz."


def test_utf8_is_read_first_and_a_byte_order_mark_is_dropped() -> None:
    assert decode_text(TURKISH.encode("utf-8-sig")) == TURKISH


def test_a_known_language_picks_its_legacy_code_page() -> None:
    assert decode_text(TURKISH.encode("cp1254"), Language("tur")) == TURKISH


def test_without_a_language_the_guess_still_returns_text() -> None:
    # The statistical guess may pick a neighbouring code page for Turkish; that is why a known language decides.
    assert "okuldan" in decode_text(TURKISH.encode("cp1254"))
