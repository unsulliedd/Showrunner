from __future__ import annotations

import threading
from pathlib import Path

import pytest

from showrunner.app.dependencies import service
from showrunner.app.settings.app_settings import load_settings
from showrunner.app.storage.paths import HOME_ENV_VAR, tools_dir
from showrunner.tools.dependencies import install as install_module
from showrunner.tools.dependencies.detect import State
from showrunner.tools.dependencies.install import Asset, DownloadPlan
from showrunner.tools.dependencies.specs import SPEC_BY_ID


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    monkeypatch.setenv("PATH", "")
    return tmp_path


def test_user_paths_are_kept_with_the_app_settings(home: Path) -> None:
    service.set_user_path("libmpv", home / "mpv" / "libmpv-2.dll")
    assert load_settings().value.tool_paths == {"libmpv": str(home / "mpv" / "libmpv-2.dll")}
    assert service.user_path("libmpv") == home / "mpv" / "libmpv-2.dll"
    service.set_user_path("libmpv", None)
    assert load_settings().value.tool_paths == {}
    assert service.user_path("libmpv") is None


def test_a_user_path_is_used_for_checking(home: Path) -> None:
    folder = home / "elsewhere"
    folder.mkdir()
    (folder / "libmpv-2.dll").write_bytes(b"")
    assert service.check(SPEC_BY_ID["libmpv"]).state is State.MISSING
    service.set_user_path("libmpv", folder)
    assert service.check(SPEC_BY_ID["libmpv"]).path == folder / "libmpv-2.dll"


def test_installing_puts_the_program_in_the_tools_folder_and_clears_the_user_path(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = SPEC_BY_ID["libmpv"]
    service.set_user_path("libmpv", home / "gone")

    def fake_install(spec_arg: object, plan: object, tools: Path, *_: object) -> Path:
        (tools / "libmpv").mkdir(parents=True)
        (tools / "libmpv" / "libmpv-2.dll").write_bytes(b"")
        return tools / "libmpv"

    monkeypatch.setattr(install_module, "install", fake_install)
    plan = DownloadPlan("libmpv", spec.source.variants[0], "1", (Asset("https://x/y.7z", "y.7z", 1, None),))
    status = service.install(plan, lambda *_: None, threading.Event(), http=object())  # type: ignore[arg-type]
    assert status.state is State.FOUND
    assert status.path == tools_dir() / "libmpv" / "libmpv-2.dll"
    assert service.user_path("libmpv") is None
