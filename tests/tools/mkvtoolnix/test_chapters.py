from __future__ import annotations

import pytest

from showrunner.core.language import Language
from showrunner.tools.mkvtoolnix.chapters import ChaptersError, parse_chapters

NESTED = """<?xml version="1.0"?>
<Chapters>
  <EditionEntry>
    <ChapterAtom>
      <ChapterTimeStart>00:01:00.500000000</ChapterTimeStart>
      <ChapterTimeEnd>01:00:00.000000000</ChapterTimeEnd>
      <ChapterDisplay><ChapterString>Part</ChapterString></ChapterDisplay>
      <ChapterAtom>
        <ChapterTimeStart>00:01:10.000000000</ChapterTimeStart>
        <ChapterDisplay><ChapterString>Inner</ChapterString><ChapterLanguage>fre</ChapterLanguage></ChapterDisplay>
      </ChapterAtom>
    </ChapterAtom>
  </EditionEntry>
  <EditionEntry>
    <ChapterAtom><ChapterTimeStart>00:00:00.000000000</ChapterTimeStart></ChapterAtom>
  </EditionEntry>
</Chapters>"""

BAD_TIME = (
    "<Chapters><EditionEntry><ChapterAtom><ChapterTimeStart>soon</ChapterTimeStart>"
    "</ChapterAtom></EditionEntry></Chapters>"
)


def test_recorded_chapters_have_a_start_and_a_name_in_their_language(recorded) -> None:
    chapters = parse_chapters(recorded("ac3_srt_turkish").chapters)
    assert len(chapters) == 7
    assert chapters[1].start == pytest.approx(139.056)
    assert chapters[1].names[0].language == Language("eng")


def test_names_come_in_every_language_and_prefer_the_ietf_tag(recorded) -> None:
    first, second, *_ = parse_chapters(recorded("flags_attachment").chapters)
    assert [(n.language.ietf, n.text) for n in first.names] == [("en", "Intro"), ("tr", "Giris")]
    assert first.name_for(Language("tur")) == "Giris"
    assert (second.start, second.end) == (2.5, 4.0)


def test_only_the_first_edition_is_read(recorded) -> None:
    assert [c.names[0].text for c in parse_chapters(recorded("flags_attachment").chapters)] == ["Intro", "Scene"]


def test_nested_chapters_are_flattened_and_a_missing_language_is_english() -> None:
    outer, inner = parse_chapters(NESTED)
    assert (outer.start, outer.end, outer.names[0].language) == (60.5, 3600.0, Language("eng"))
    assert (inner.start, inner.end, inner.names[0].language) == (70.0, None, Language("fra"))


def test_xml_without_chapters_gives_none() -> None:
    assert parse_chapters("<Chapters/>") == ()


@pytest.mark.parametrize("xml", ["not xml", "<Chapters><EditionEntry><ChapterAtom>", BAD_TIME])
def test_text_that_is_not_chapter_xml_is_an_error(xml: str) -> None:
    with pytest.raises(ChaptersError):
        parse_chapters(xml)
