# ruff: noqa: RUF001 (Turkish letters are the point of this data)
"""Re-split by timing: the words of each line moved onto the reference cues it is said over, cut in proportion and at
punctuation, every word kept once and in order."""

from __future__ import annotations

import random

import pytest

from showrunner.core.cue import Cue
from showrunner.stages.subtitles.resplit import PULLS, Tuning, accepts, by_timing, plain_words


def words(cues: list[Cue]) -> list[str]:
    return [word for cue in cues for word in plain_words(cue.text)]


def test_a_line_over_two_cues_is_cut_in_proportion_to_its_overlap_with_each() -> None:
    reference = [Cue(0.0, 1.0, "Go."), Cue(1.0, 4.0, "Run to the house and hide.")]
    line = Cue(0.0, 4.0, "bir iki üç dört beş altı yedi sekiz")
    result = by_timing([line], reference).cues()
    assert [(cue.start, cue.end) for cue in result] == [(0.0, 1.0), (1.0, 4.0)]
    # A quarter of the time, so about a quarter of the text.
    assert result[0].text == "bir iki"
    assert result[1].text == "üç dört beş altı yedi sekiz"


def test_a_cut_moves_to_punctuation_nearby() -> None:
    reference = [Cue(0.0, 2.0, "Hello there."), Cue(2.0, 4.0, "How are you?")]
    line = Cue(0.0, 4.0, "Merhaba dostum, nasılsın bugün?")
    result = by_timing([line], reference).cues()
    assert [cue.text for cue in result] == ["Merhaba dostum,", "nasılsın bugün?"]


def test_a_cut_prefers_another_speaker() -> None:
    # By time alone the cut would fall after "-Eve".
    reference = [Cue(0.0, 2.8, "- Where are you going?"), Cue(2.8, 4.0, "- Home.")]
    line = Cue(0.0, 4.0, "-Nereye gidiyorsun\n-Eve dönüyorum")
    result = by_timing([line], reference).cues()
    assert [cue.text for cue in result] == ["-Nereye gidiyorsun", "-Eve dönüyorum"]


def test_two_lines_on_one_cue_are_joined_and_put_on_its_lines() -> None:
    reference = [Cue(0.0, 4.0, "I told you\nnot to touch that.")]
    lines = [Cue(0.0, 2.0, "Sana söyledim,"), Cue(2.1, 4.0, "ona dokunma dedim.")]
    result = by_timing(lines, reference).cues()
    assert result == [Cue(0.0, 4.0, "Sana söyledim,\nona dokunma dedim.")]


def test_a_short_text_stays_on_one_line_and_a_long_one_goes_on_two() -> None:
    reference = [Cue(0.0, 2.0, "Yes,\nsir.")]
    assert by_timing([Cue(0.0, 2.0, "Evet efendim.")], reference).cues()[0].text == "Evet efendim."
    long = "Bunu sana kaç kere söyledim ama sen hiç dinlemedin beni"
    one_line = [Cue(0.0, 2.0, "Fine.")]
    assert by_timing([Cue(0.0, 2.0, long)], one_line).cues()[0].text.count("\n") == 1


def test_speakers_each_get_a_line() -> None:
    reference = [Cue(0.0, 2.0, "- Hi. - Hello.")]
    result = by_timing([Cue(0.0, 2.0, "- Selam. - Merhaba.")], reference).cues()
    assert result[0].text == "- Selam.\n- Merhaba."


def test_a_line_over_no_cue_keeps_its_own_timing_and_text() -> None:
    reference = [Cue(0.0, 1.0, "One."), Cue(5.0, 6.0, "Two.")]
    lines = [Cue(0.0, 1.0, "Bir."), Cue(2.0, 3.0, "Şarkı\nsözü"), Cue(5.0, 6.0, "İki.")]
    result = by_timing(lines, reference).cues()
    assert result == [Cue(0.0, 1.0, "Bir."), Cue(2.0, 3.0, "Şarkı\nsözü"), Cue(5.0, 6.0, "İki.")]


def test_a_clip_at_a_cue_s_edge_is_a_sync_error_not_the_line() -> None:
    reference = [Cue(0.0, 2.0, "First line."), Cue(2.0, 4.0, "Second line.")]
    # Runs 0.2 s into the second cue.
    lines = [Cue(0.0, 2.2, "Birinci satır."), Cue(2.2, 4.0, "İkinci satır.")]
    result = by_timing(lines, reference).cues()
    assert [cue.text for cue in result] == ["Birinci satır.", "İkinci satır."]


def test_fewer_words_than_cues_lend_the_empty_cue_s_time() -> None:
    reference = [Cue(0.0, 1.0, "Wait."), Cue(1.0, 2.0, "Wait!")]
    result = by_timing([Cue(0.0, 2.0, "Bekle!")], reference).cues()
    assert result == [Cue(0.0, 2.0, "Bekle!")]


def test_an_italic_line_cut_in_two_stays_italic_in_both() -> None:
    reference = [Cue(0.0, 2.0, "Once upon"), Cue(2.0, 4.0, "a time.")]
    result = by_timing([Cue(0.0, 4.0, r"{\an8}{\i1}Bir varmış bir yokmuş{\i0}")], reference).cues()
    assert result[0].text.startswith(r"{\an8}{\i1}")
    assert result[1].text.startswith(r"{\an8\i1}")
    assert words(result) == ["Bir", "varmış", "bir", "yokmuş"]


def test_a_reference_cue_given_to_no_line_is_left_out() -> None:
    reference = [Cue(0.0, 1.0, "Hi."), Cue(1.0, 2.0, "[DOOR SLAMS]"), Cue(2.0, 3.0, "Bye.")]
    lines = [Cue(0.0, 1.0, "Selam."), Cue(2.0, 3.0, "Hoşça kal.")]
    assert [cue.text for cue in by_timing(lines, reference).cues()] == ["Selam.", "Hoşça kal."]


def test_empty_lines_and_lines_of_markup_hold_nothing_to_move() -> None:
    reference = [Cue(0.0, 1.0, "Hi.")]
    lines = [Cue(0.0, 1.0, ""), Cue(0.0, 1.0, r"{\i1}{\i0}"), Cue(0.0, 1.0, "Selam.")]
    assert by_timing(lines, reference).cues() == [Cue(0.0, 1.0, "Selam.")]


def test_no_reference_keeps_every_line() -> None:
    lines = [Cue(0.0, 1.0, "Bir."), Cue(1.0, 2.0, "İki.")]
    assert by_timing(lines, []).cues() == lines


@pytest.mark.parametrize("seed", range(300))
def test_every_word_is_kept_once_and_in_order(seed: int) -> None:
    """Random lines and cues, overlapping, nested, of no length, out of order: the words come out as they went in."""
    rng = random.Random(seed)

    def cues(count: int, prefix: str) -> list[Cue]:
        found = []
        for number in range(count):
            start = rng.uniform(0, 60)
            length = rng.choice([0.0, rng.uniform(0.05, 0.5), rng.uniform(0.5, 8)])
            text = " ".join(
                rng.choice([f"{prefix}{number}w{word}", f"{prefix}{number}w{word}.", "-", r"{\i1}x", r"y{\i0}"])
                for word in range(rng.randint(0, 9))
            )
            if rng.random() < 0.3:
                text = text.replace(" ", "\n", 1)
            found.append(Cue(start, start + length, text))
        if rng.random() < 0.7:
            found.sort(key=lambda cue: cue.start)
        return found

    lines = cues(rng.randint(0, 25), "t")
    # Any values in range keep the words as well.
    tuning = Tuning(rng.randint(20, 80), rng.randint(0, 80), rng.uniform(0, 2), rng.choice(list(PULLS)))
    layout = by_timing(lines, cues(rng.randint(0, 25), "e"), tuning)
    result = layout.cues()
    assert words(result) == words(lines)
    assert all(cue.end >= cue.start for cue in result)
    assert sum(unit.count for unit in layout.units) == len(layout.words)


def test_new_counts_move_only_the_cuts() -> None:
    reference = [Cue(0.0, 2.0, "A"), Cue(2.0, 4.0, "B")]
    layout = by_timing([Cue(0.0, 4.0, "bir iki üç dört")], reference)
    moved = layout.with_counts([3, 1]).cues()
    assert [cue.text for cue in moved] == ["bir iki üç", "dört"]
    with pytest.raises(ValueError, match="words placed"):
        layout.with_counts([3, 2])


def test_no_word_moves_across_a_kept_line() -> None:
    reference = [Cue(0.0, 1.0, "A"), Cue(5.0, 6.0, "B")]
    lines = [Cue(0.0, 1.0, "bir iki"), Cue(2.0, 3.0, "kendi"), Cue(5.0, 6.0, "üç")]
    layout = by_timing(lines, reference)
    assert layout.barriers() == frozenset({1})
    with pytest.raises(ValueError, match="kept line"):
        layout.with_counts([1, 2])


def test_the_values_are_read_from_the_settings_and_one_that_cannot_be_taken_is_its_default() -> None:
    settings = {"timing.longest_line": "37", "timing.smallest_overlap": "0.5", "timing.punctuation": "strong"}
    assert Tuning.read(settings) == Tuning(longest_line=37, smallest_overlap=0.5, punctuation="strong")
    wrong = {"timing.longest_line": "5", "timing.two_lines_from": "many", "timing.punctuation": "loud", "window": "9"}
    assert Tuning.read(wrong) == Tuning()


@pytest.mark.parametrize(
    ("key", "text", "taken"),
    [
        ("timing.longest_line", "", True),
        ("timing.longest_line", "37", True),
        ("timing.longest_line", "19", False),
        ("timing.longest_line", "37.5", False),
        ("timing.smallest_overlap", "0.5", True),
        ("timing.smallest_overlap", "3", False),
        ("timing.punctuation", "weak", True),
        ("timing.punctuation", "loud", False),
        ("ai.window", "20", True),
        ("ai.window", "1", False),
        ("ai.other", "1", False),
        ("other.longest_line", "37", False),
    ],
)
def test_a_value_is_taken_only_within_its_range_or_choices(key: str, text: str, taken: bool) -> None:
    assert accepts(key, text) is taken


def test_the_longest_line_decides_where_a_text_wraps() -> None:
    reference = [Cue(0.0, 2.0, "One line.")]
    text = "Bunu yarın sabah erkenden yapacağız."  # 36 characters
    assert "\n" not in by_timing([Cue(0.0, 2.0, text)], reference).cues()[0].text
    assert by_timing([Cue(0.0, 2.0, text)], reference, Tuning(longest_line=30)).cues()[0].text.count("\n") == 1


def test_two_lines_from_decides_when_a_two_line_cue_gets_two() -> None:
    reference = [Cue(0.0, 2.0, "Two\nlines.")]
    text = "Yarın sabah gidiyoruz."  # 22 characters
    assert "\n" not in by_timing([Cue(0.0, 2.0, text)], reference).cues()[0].text
    assert by_timing([Cue(0.0, 2.0, text)], reference, Tuning(two_lines_from=10)).cues()[0].text.count("\n") == 1


def test_a_larger_smallest_overlap_leaves_a_short_overlap_out() -> None:
    reference = [Cue(0.0, 2.0, "First."), Cue(2.0, 4.0, "Second.")]
    line = Cue(0.0, 2.4, "bir iki üç dört")  # 0.4 s over the second cue
    assert len(by_timing([line], reference).cues()) == 2
    assert len(by_timing([line], reference, Tuning(smallest_overlap=0.5)).cues()) == 1


def test_a_stronger_pull_moves_a_cut_further_to_punctuation() -> None:
    reference = [Cue(0.0, 3.0, "A."), Cue(3.0, 4.0, "B.")]
    line = Cue(0.0, 4.0, "Bir iki. üç dört beş altı yedi sekiz")
    weak = by_timing([line], reference, Tuning(punctuation="weak")).cues()
    strong = by_timing([line], reference, Tuning(punctuation="strong")).cues()
    assert strong[0].text == "Bir iki."
    assert weak[0].text != "Bir iki."
