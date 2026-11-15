from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.app.storage.paths import HOME_ENV_VAR


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The window saves settings and the theme as the user changes them; tests must never touch the real data folder.
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    return tmp_path
