"""Rules read from small hand-made files in the shapes Subtitle Edit writes."""

from __future__ import annotations

import pytest

from showrunner.core.language import Language
from showrunner.tools.cleanit import (
    NotSubtitleEditError,
    RuleKind,
    clean_text,
    language_of,
    read_file,
)
from showrunner.tools.cleanit.engine import compile_sets

MULTIPLE = r"""<?xml version="1.0" encoding="utf-8"?>
<Settings>
  <Tools><Other>1</Other></Tools>
  <MultipleSearchAndReplaceGroups>
    <Group>
      <Name>My fixes</Name>
      <Enabled>true</Enabled>
      <Rule>
        <Enabled>true</Enabled>
        <FindWhat>colour</FindWhat>
        <ReplaceWith>color</ReplaceWith>
        <SearchType>Normal</SearchType>
        <Description>US spelling</Description>
      </Rule>
      <Rule>
        <Enabled>false</Enabled>
        <FindWhat>Cat</FindWhat>
        <ReplaceWith>Dog</ReplaceWith>
        <SearchType>CaseSensitive</SearchType>
        <WholeWord>true</WholeWord>
      </Rule>
      <Rule>
        <Enabled>true</Enabled>
        <FindWhat>(?&lt;first&gt;\w+)-(?&lt;second&gt;\w+)</FindWhat>
        <ReplaceWith>${second} $1 $$</ReplaceWith>
        <SearchType>RegularExpression</SearchType>
      </Rule>
      <Rule>
        <Enabled>true</Enabled>
        <FindWhat>\p{L}+</FindWhat>
        <ReplaceWith>x</ReplaceWith>
        <SearchType>RegularExpression</SearchType>
      </Rule>
      <Rule><Enabled>true</Enabled><FindWhat>a</FindWhat><ReplaceWith>b</ReplaceWith><SearchType>Fuzzy</SearchType></Rule>
      <Rule><Enabled>true</Enabled><FindWhat></FindWhat></Rule>
    </Group>
    <Group><Name>Off</Name><Enabled>false</Enabled>
      <Rule><FindWhat>x</FindWhat><ReplaceWith>y</ReplaceWith></Rule>
    </Group>
  </MultipleSearchAndReplaceGroups>
</Settings>
"""
OCR = """<?xml version="1.0" encoding="utf-8"?>
<OCRFixReplaceList>
  <WholeWords><Word from="l'm" to="I'm" /><Word from="" to="x" /></WholeWords>
  <PartialWordsAlways><WordPart from="¤" to="o" /></PartialWordsAlways>
  <PartialWords><WordPart from="IVI" to="M" /></PartialWords>
  <WholeLines><Line from="H ey." to="Hey." /></WholeLines>
  <PartialLinesAlways><LinePart from="forbest" to="for best" /></PartialLinesAlways>
  <PartialLines><LinePart from=" /be " to=" I be " /></PartialLines>
  <BeginLines><Beginning from="lgot" to="I got" /></BeginLines>
  <EndLines><Ending from=", sin" to=", sir." /></EndLines>
  <RegularExpressions><RegEx find="([a-z]) Won't " replaceWith="$1 won't " /></RegularExpressions>
  <RegularExpressionsIfSpelledCorrectly>
    <RegEx find="a" replaceWith="b" spellCheck="$1" />
  </RegularExpressionsIfSpelledCorrectly>
</OCRFixReplaceList>
"""
ENGLISH = Language("eng")


def clean(rule_set, text: str) -> str | None:
    return clean_text(text, compile_sets([rule_set], ENGLISH))[0]


def test_a_group_becomes_a_set_and_what_cannot_be_carried_over_is_listed() -> None:
    imported = read_file(MULTIPLE.encode(), taken=["My-fixes"])
    names = [s.name for s in imported.sets]
    assert names == ["My-fixes-2", "Off"]  # the name "My-fixes" was taken
    assert [r.paused for r in imported.sets[1].rules] == [True]  # a group that is off pauses its rules
    rules = imported.sets[0].rules
    assert [r.name for r in rules] == ["US spelling", "Cat", r"(?<first>\w+)-(?<second>\w+)"]
    assert [r.paused for r in rules] == [False, True, False]
    assert {(s.where, s.reason) for s in imported.skipped} >= {
        ("My fixes", "dotnet-regex"),
        ("My fixes", "unknown-type"),
        ("My fixes", "empty"),
    }
    assert len(imported.skipped) == 3


def test_the_imported_rules_do_what_subtitle_edit_would() -> None:
    imported = read_file(MULTIPLE.encode())
    rule_set = imported.sets[0]
    assert clean(rule_set, "A COLOUR test") == "A color test"  # Normal ignores case
    assert rule_set.rules[0].kind is RuleKind.TEXT
    assert clean(rule_set, "hello-world") == "world hello $"  # $1, ${name} and $$


def test_an_older_list_without_groups_is_one_group() -> None:
    text = (
        "<Settings><MultipleSearchAndReplaceList><MultipleSearchAndReplaceItem><Enabled>True</Enabled>"
        r"<FindWhat>a\nb</FindWhat><ReplaceWith>c\d</ReplaceWith><SearchType>CaseSensitive</SearchType>"
        "</MultipleSearchAndReplaceItem></MultipleSearchAndReplaceList></Settings>"
    )
    (rule_set,) = read_file(text.encode()).sets
    assert rule_set.name == "Subtitle-Edit-1"
    assert clean(rule_set, "x a\nb y") == r"x c\d y"  # a backslash in the replacement is literal


def test_ocr_lists_become_rules_for_the_language_of_the_file() -> None:
    imported = read_file(OCR.encode(), language="en")
    assert imported.sets == ()
    assert {r.languages for r in imported.ocr} == {("en",)}
    assert {s.reason for s in imported.skipped} == {"spelling"}
    assert len(imported.skipped) == 3  # PartialWords, PartialLines, the spelled-correctly expressions
    book = {r.name.split(":")[0]: r for r in imported.ocr}
    assert set(book) == {
        "WholeWords",
        "PartialWordsAlways",
        "WholeLines",
        "PartialLinesAlways",
        "BeginLines",
        "EndLines",
        "RegularExpressions",
    }
    from showrunner.tools.cleanit import RuleSet  # the rules run together, as the OCR fixes do

    fixes = RuleSet("ocr-fixes", imported.ocr)
    assert clean(fixes, "l'm here") == "I'm here"
    assert clean(fixes, "l'mhere") == "l'mhere"  # whole words only
    assert clean(fixes, "H ey.") == "Hey."
    assert clean(fixes, "lgot it") == "I got it"
    assert clean(fixes, "yes, sin") == "yes, sir."
    assert clean(fixes, "a Won't ") == "a won't"


def test_a_file_that_is_not_subtitle_edits_is_refused() -> None:
    for text in ("<Settings/>", "not xml", "<a><b/></a>"):
        with pytest.raises(NotSubtitleEditError):
            read_file(text.encode())


def test_the_language_comes_from_the_file_name() -> None:
    assert language_of("eng_OCRFixReplaceList.xml") == "en"
    assert language_of("por_OCRFixReplaceList_User.xml") == "pt"
    assert language_of("Settings.xml") == ""
