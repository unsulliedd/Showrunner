from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from showrunner.tools.process import RunResult

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class Recorded:
    """The output of mkvmerge -J, ffprobe and mkvextract for one real file, with paths and ids removed."""

    mkvmerge: dict[str, Any]
    ffprobe: dict[str, Any]
    chapters: str | None


@dataclass
class FakeTools:
    """Stands in for the three programs: `run` answers from the recorded output and remembers every call."""

    recorded: Recorded
    mkvmerge_exit: int = 0
    ffprobe_exit: int = 0
    frames: dict[str, Any] = field(default_factory=lambda: {"frames": []})
    calls: list[str] = field(default_factory=list)

    def run(self, args: Any, **_: Any) -> RunResult:
        command = tuple(str(a) for a in args)
        name = Path(command[0]).stem
        kind = "frames" if "-show_frames" in command else name
        self.calls.append(kind)
        if name == "mkvmerge":
            return RunResult(command, self.mkvmerge_exit, json.dumps(self.recorded.mkvmerge), "")
        if name == "mkvextract":
            return RunResult(command, 0, self.recorded.chapters or "", "")
        if self.ffprobe_exit:
            return RunResult(command, self.ffprobe_exit, "", "Invalid data found")
        data = self.frames if kind == "frames" else self.recorded.ffprobe
        return RunResult(command, 0, json.dumps(data), "")


@pytest.fixture
def recorded() -> Callable[[str], Recorded]:
    """Loads a recorded file by folder name; a fresh copy each time, so a test may edit it."""

    def load(name: str) -> Recorded:
        folder = FIXTURES / name
        chapters = folder / "chapters.xml"
        return Recorded(
            copy.deepcopy(json.loads((folder / "mkvmerge.json").read_text(encoding="utf-8"))),
            copy.deepcopy(json.loads((folder / "ffprobe.json").read_text(encoding="utf-8"))),
            chapters.read_text(encoding="utf-8") if chapters.is_file() else None,
        )

    return load


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> Callable[[Recorded], FakeTools]:
    """Routes every program run of the adapters to a FakeTools."""

    def install(data: Recorded) -> FakeTools:
        tools = FakeTools(data)
        for module in ("mkvtoolnix.identify", "mkvtoolnix.chapters", "ffmpeg.ffprobe"):
            monkeypatch.setattr(f"showrunner.tools.{module}.run", tools.run)
        return tools

    return install


@pytest.fixture
def media_file(tmp_path: Path) -> Path:
    """A file that exists; the programs are faked, so its content does not matter."""
    path = tmp_path / "episode.mkv"
    path.write_bytes(b"x" * 10)
    return path
