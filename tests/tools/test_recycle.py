"""The checks that stop a recycle before the shell is asked. The shell itself is never called here: a test must
not put files in the user's Recycle Bin."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from showrunner.tools import recycle as module
from showrunner.tools.recycle import RecycleError, recycle

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the Recycle Bin is a Windows feature")


@pytest.fixture
def no_shell(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    monkeypatch.setattr(ctypes.windll.shell32, "SHFileOperationW", lambda *args: calls.append(args) or 1)
    return calls


def kernel(monkeypatch: pytest.MonkeyPatch, name: str, value: Callable[..., int]) -> None:
    monkeypatch.setattr(ctypes.windll.kernel32, name, value)


def test_a_drive_without_a_recycle_bin_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_shell: list[object]
) -> None:
    video = tmp_path / "Episode One.mkv"
    video.write_bytes(b"x")
    kernel(monkeypatch, "GetDriveTypeW", lambda _root: 4)  # a network share
    with pytest.raises(RecycleError, match="no Recycle Bin"):
        recycle([video])
    assert video.exists()
    assert not no_shell


def test_a_bin_set_to_delete_at_once_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_shell: list[object]
) -> None:
    video = tmp_path / "Episode One.mkv"
    video.write_bytes(b"x")
    monkeypatch.setattr(module, "_bin_settings", lambda _volume: {"NukeOnDelete": 1})
    with pytest.raises(RecycleError, match="at once"):
        recycle([video])
    assert not no_shell


def test_a_file_larger_than_the_bin_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_shell: list[object]
) -> None:
    video = tmp_path / "Episode One.mkv"
    video.write_bytes(b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr(module, "_bin_settings", lambda _volume: {"MaxCapacity": 1})
    with pytest.raises(RecycleError, match="larger"):
        recycle([video])
    assert not no_shell


def test_a_shell_failure_is_reported_and_the_file_stays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_shell: list[object]
) -> None:
    video = tmp_path / "Episode One.mkv"
    video.write_bytes(b"x")
    monkeypatch.setattr(module, "_bin_settings", lambda _volume: {})
    with pytest.raises(RecycleError, match="did not move"):
        recycle([video])
    assert video.exists()
    assert len(no_shell) == 1
