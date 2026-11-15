from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from showrunner.core.language import Language
from showrunner.core.track import TrackFlags, TrackKind
from showrunner.tools.mkvtoolnix import merge as merging
from showrunner.tools.mkvtoolnix.merge import Merge, MergeError, OutputTrack, build_arguments, iconv_name, merge
from showrunner.tools.process import RunResult

SPEC = Merge(
    Path("out.mkv"),
    (Path("video.mkv"), Path("video.tr.srt")),
    (
        OutputTrack(0, 0, TrackKind.VIDEO, "Video", None, TrackFlags(default=True)),
        OutputTrack(0, 2, TrackKind.AUDIO, "English", Language("eng"), TrackFlags(default=True, commentary=True)),
        OutputTrack(1, 0, TrackKind.SUBTITLE, "Turkish", Language("tur"), TrackFlags(forced=True), "cp1254"),
    ),
    "Episode One",
)


def flags(arguments: list[str], track_id: int) -> dict[str, str]:
    """Option -> value for one track ID, read from pairs like `--forced-display-flag 0:1`."""
    return {
        arguments[i]: arguments[i + 1].split(":", 1)[1]
        for i in range(len(arguments) - 1)
        if arguments[i].endswith("-flag") and arguments[i + 1].startswith(f"{track_id}:")
    }


def test_arguments_select_tracks_per_source_and_set_every_value() -> None:
    arguments = build_arguments(SPEC)
    assert arguments[:7] == ["--ui-language", "en", "--gui-mode", "--output", "out.mkv", "--title", "Episode One"]
    video = arguments.index("video.mkv")
    first = arguments[:video]
    assert first[first.index("--video-tracks") + 1] == "0"
    assert first[first.index("--audio-tracks") + 1] == "2"
    assert "--no-subtitles" in first
    assert "--track-name" in first
    assert "2:English" in first
    assert "2:en" in first
    assert "0:und" in first
    second = arguments[video + 1 : arguments.index("video.tr.srt")]
    assert "--no-video" in second
    assert "--no-audio" in second
    assert second[second.index("--sub-charset") + 1] == "0:cp1254"
    assert arguments[-2:] == ["--track-order", "0:0,0:2,1:0"]


def test_every_flag_is_passed_with_its_value() -> None:
    # mkvmerge would otherwise make an added subtitle a default track.
    arguments = build_arguments(SPEC)
    subtitle_flags = flags(arguments[arguments.index("video.mkv") :], 0)
    assert subtitle_flags == {
        "--default-track-flag": "0",
        "--forced-display-flag": "1",
        "--hearing-impaired-flag": "0",
        "--visual-impaired-flag": "0",
        "--commentary-flag": "0",
        "--original-flag": "0",
    }


def test_iconv_names_use_dashes() -> None:
    assert iconv_name("euc_kr") == "euc-kr"
    assert iconv_name("cp1254") == "cp1254"


def fake(monkeypatch: pytest.MonkeyPatch, lines: list[str], code: int) -> list[Any]:
    calls: list[Any] = []

    def run(args: Any, **kwargs: Any) -> RunResult:
        calls.append(kwargs)
        for line in lines:
            kwargs["on_line"](line)
        return RunResult(tuple(map(str, args)), code, "\n".join(lines), "")

    monkeypatch.setattr(merging, "run", run)
    return calls


def test_progress_is_read_from_gui_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake(monkeypatch, ["Opening...", "#GUI#progress 40%", "#GUI#progress 100%"], 0)
    seen: list[float] = []
    assert merge(Path("mkvmerge"), SPEC, progress=seen.append).warnings == ()
    assert seen == [0.4, 1.0]
    assert calls[0].get("timeout") is None  # a large file takes as long as the disk needs


def test_exit_code_one_is_warnings_and_the_file_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, ["#GUI#warning Track 2: the frame rate is odd."], 1)
    assert merge(Path("mkvmerge"), SPEC).warnings == ("Track 2: the frame rate is odd.",)


def test_exit_code_two_is_an_error_with_the_programs_words(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, ["#GUI#error The file 'video.tr.srt' could not be opened for reading."], 2)
    with pytest.raises(MergeError, match="could not be opened"):
        merge(Path("mkvmerge"), SPEC)


def test_a_subtitle_that_was_not_converted_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Garbled subtitle text would go into the new file while the original goes to the bin.
    fake(monkeypatch, ["#GUI#warning 'x.srt' track 0: This text subtitle track contains invalid 8-bit characters."], 1)
    with pytest.raises(MergeError, match="8-bit"):
        merge(Path("mkvmerge"), SPEC)


def test_a_missing_program_is_a_merge_error(tmp_path: Path) -> None:
    with pytest.raises(MergeError):
        merge(tmp_path / "mkvmerge.exe", SPEC)
