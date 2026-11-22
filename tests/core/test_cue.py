import dataclasses
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language


def test_midpoint() -> None:
    assert Cue(1.0, 3.0, "Hi").midpoint == 2.0


def test_cue_is_immutable_and_copied_with_replace() -> None:
    cue = Cue(1.0, 3.0, "Hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cue.start = 2.0  # type: ignore[misc]
    assert dataclasses.replace(cue, start=2.0).midpoint == 2.5


def test_srt_reads_into_cues_with_line_breaks_and_italics(tmp_path: Path) -> None:
    path = tmp_path / "a.srt"
    path.write_bytes(b"1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>Hello</i>\r\nworld\r\n\r\n")
    assert read_cues(path) == [Cue(1.0, 2.5, "{\\i1}Hello{\\i0}\nworld")]


def test_legacy_code_page_is_read_by_language(tmp_path: Path) -> None:
    path = tmp_path / "a.srt"
    path.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nŞimdi gitmeliyiz\n".encode("cp1254"))
    assert read_cues(path, Language.parse("tr"))[0].text == "Şimdi gitmeliyiz"


@pytest.mark.parametrize("suffix", [".srt", ".vtt", ".ass"])
def test_cues_round_trip(tmp_path: Path, suffix: str) -> None:
    cues = [Cue(0.5, 1.25, "{\\i1}One{\\i0}\nline"), Cue(2.0, 3.0, "Two")]
    path = tmp_path / f"out{suffix}"
    write_cues(path, cues)
    back = read_cues(path)
    assert [(c.start, c.end, c.text) for c in back] == [(c.start, c.end, c.text) for c in cues]
    assert path.read_bytes().decode("utf-8")  # always written as UTF-8


def test_ass_keeps_styles_and_comments_are_not_cues(tmp_path: Path) -> None:
    source = tmp_path / "in.ass"
    write_cues(source, [Cue(1.0, 2.0, "Hi")])
    text = source.read_text(encoding="utf-8")
    text = text.replace(
        "Style: Default,",
        "Style: Sign,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,"
        "100,100,0,0,1,2,2,8,10,10,10,1\nStyle: Default,",
    )
    text += "Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,a note\n"
    text += "Dialogue: 0,0:00:05.00,0:00:06.00,Sign,,0,0,0,,EXIT\n"
    source.write_text(text, encoding="utf-8")
    cues = read_cues(source)
    assert [(c.text, c.style) for c in cues] == [("Hi", "Default"), ("EXIT", "Sign")]

    result = tmp_path / "out.ass"
    write_cues(result, [replace(cue, text=cue.text.upper()) for cue in cues], like=source)
    assert [(c.text, c.style) for c in read_cues(result)] == [("HI", "Default"), ("EXIT", "Sign")]
    assert "Style: Sign," in result.read_text(encoding="utf-8")


def test_other_formats_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r".sup"):
        read_cues(tmp_path / "a.sup")
    with pytest.raises(ValueError, match=r".sub"):
        write_cues(tmp_path / "a.sub", [])
