"""The programs the window checks at startup."""

from __future__ import annotations

from typing import Any

import pytest

from showrunner.ui.quick import found


def test_the_window_checks_tesseract_too_since_plans_need_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(found, "check", lambda spec, *args, **kwargs: spec.id)
    checked: dict[str, Any] = found.check_shown()
    assert "tesseract" in checked
    # The status bar still shows only the programs that read and write the files.
    assert found.SHOWN_PROGRAMS == ("mkvtoolnix", "ffmpeg")
