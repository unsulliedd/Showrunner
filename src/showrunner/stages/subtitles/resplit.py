"""Re-split by timing: a subtitle's own words moved onto the reference's cues, so a translation with bad timing or badly
split lines takes the original's timing and line breaks.

Each line of the subtitle goes to the reference cues it overlaps, and a line over several cues is cut at word boundaries
in proportion to how long it overlaps each, a cut at punctuation or before another speaker preferred. A line no
reference cue overlaps keeps its own timing and text. The result is built in the order of the subtitle's words, a line
never given a cue before one an earlier line was given, so no word is added, dropped or moved: only where the cuts fall
changes. The AI way moves only those cuts, within a window of reference cues (`Layout.with_counts`).

Pure and offline: the same files give the same result.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from itertools import accumulate, pairwise

from showrunner.core.cue import Cue
from showrunner.tools.sync import Setting, SettingKind

# How much nearer a cut lies to where the timing puts it than a cut at punctuation, as a share of the line's length,
# before the punctuation is passed over. Large, since translated lines stay on screen past their speech and so reach
# into the next cue: measured on real files, a cue's sentence end matched more often up to these and no more beyond.
_SPEAKER, _STRONG, _WEAK = 0.5, 0.45, 0.2
# The pull towards punctuation each choice of its setting gives, as a factor on the three above.
PULLS = {"weak": 0.5, "normal": 1.0, "strong": 1.5}
# The prefix of the timing's settings, which re-split with AI starts from and so uses too, and of the AI way's own.
TIMING, AI = "timing", "ai"
# The AI way's own setting: the reference cues the model sees at a time; empty is translation's window in Settings.
AI_WINDOW = "window"
_AI_WINDOW_RANGE = (2, 200)


@dataclass(frozen=True, slots=True)
class Tuning:
    """The values re-split by timing works with; the defaults are the ones measured on real files."""

    # A text longer than this goes on two lines whatever the reference cue has: a longer line does not fit most screens.
    longest_line: int = field(default=42, metadata={"range": (20, 80)})
    # A text longer than this goes on two lines where the reference cue has two or more; a short one stays on one.
    two_lines_from: int = field(default=24, metadata={"range": (0, 80)})
    # An overlap shorter than this, and shorter than half of the shorter of the two, is a sync's error at a cue's edge,
    # not the line being said over that cue; it counts only where the line overlaps nothing else.
    smallest_overlap: float = field(default=0.3, metadata={"range": (0.0, 2.0)})
    punctuation: str = field(default="normal", metadata={"choices": tuple(PULLS)})

    @classmethod
    def read(cls, settings: Mapping[str, str]) -> Tuning:
        """The values among `settings` under `timing.`; one missing, or one that cannot be taken, is its default."""
        given: dict[str, object] = {}
        for item in fields(cls):
            text = settings.get(f"{TIMING}.{item.name}", "")
            if text and accepts(f"{TIMING}.{item.name}", text):
                given[item.name] = text if item.type == "str" else _number(str(item.type), text)
        return cls(**given)  # type: ignore[arg-type]


def resplit_settings() -> list[tuple[str, Setting]]:
    """Every setting of re-split under its full key, the timing's first and the AI way's last."""
    found = []
    for item in fields(Tuning):
        choices = item.metadata.get("choices")
        kind = SettingKind.CHOICE if choices else SettingKind.NUMBER
        # A choice's empty value is its default, so the default is not among the others.
        others = tuple(choice for choice in choices if choice != item.default) if choices else ()
        found.append((f"{TIMING}.{item.name}", Setting(item.name, kind, str(item.default), others)))
    found.append((f"{AI}.{AI_WINDOW}", Setting(AI_WINDOW, SettingKind.NUMBER, "")))
    return found


def accepts(key: str, text: str) -> bool:
    """Whether `text` can be the value of the setting under `key`: empty, one of its choices, or a number in its
    range."""
    if not text:
        return True
    way, _, name = key.partition(".")
    if way == AI:
        return name == AI_WINDOW and _in_range("int", text, _AI_WINDOW_RANGE)
    item = next((item for item in fields(Tuning) if item.name == name), None) if way == TIMING else None
    if item is None:
        return False
    if "choices" in item.metadata:
        return text in item.metadata["choices"]
    return _in_range(str(item.type), text, item.metadata["range"])


def _in_range(kind: str, text: str, bounds: tuple[float, float]) -> bool:
    try:
        value = _number(kind, text)
    except ValueError:
        return False
    return bounds[0] <= value <= bounds[1]


def _number(kind: str, text: str) -> float:
    return int(text) if kind == "int" else float(text)


_OVERRIDE = re.compile(r"\{[^}]*\}")
_TAG = re.compile(r"\\an(\d)|\\([ibu])(\d)")
_CLOSING = "\"'»”’)]"  # noqa: RUF001


@dataclass(frozen=True, slots=True)
class Unit:
    """One cue of the result, in the order of the words: a reference cue with the words given to it, or a line that
    overlaps none, kept as it is."""

    start: float
    end: float
    first: int  # the first of its words in `Layout.words`
    count: int
    slot: int | None  # the reference cue, in `Layout.reference`; None for a line kept as it is
    style: str = ""
    text: str = ""  # a kept line's own text
    # The reference cue and the one before it are given to one line, so an empty one lends its time to its neighbour.
    joined: bool = False


@dataclass(frozen=True, slots=True)
class Layout:
    words: tuple[str, ...]  # every word of the subtitle in order, with the markup it carries
    # Per word: the markup a cue that starts at it opens, so an italic line cut in two stays italic in both.
    carry: tuple[str, ...]
    units: tuple[Unit, ...]
    reference: tuple[Cue, ...]  # the reference's cues with a length, by time
    tuning: Tuning = Tuning()

    def slots(self) -> list[Cue]:
        """The reference cues given words, in order, each with its words: what the AI way redistributes."""
        return [
            Cue(unit.start, unit.end, " ".join(self.words[unit.first : unit.first + unit.count]))
            for unit in self.units
            if unit.slot is not None
        ]

    def slot_references(self) -> list[Cue]:
        """The reference cue of each slot, in the order of `slots`."""
        return [self.reference[unit.slot] for unit in self.units if unit.slot is not None]

    def barriers(self) -> frozenset[int]:
        """The slots a kept line comes before: no word may move across one, since the kept line's words lie between."""
        found, slot, kept = set(), 0, False
        for unit in self.units:
            if unit.slot is None:
                kept = True
            else:
                if kept:
                    found.add(slot)
                slot, kept = slot + 1, False
        return frozenset(found)

    def with_counts(self, counts: Sequence[int]) -> Layout:
        """The same layout with another number of words in each slot, in order. Raises `ValueError` where the counts do
        not hold every word between two kept lines."""
        slots = iter(counts)
        units, first = [], 0
        for unit in self.units:
            count = unit.count if unit.slot is None else next(slots)
            if unit.slot is None and first != unit.first:
                raise ValueError(f"a kept line starts at word {first}, not {unit.first}")
            units.append(replace(unit, first=first, count=count))
            first += count
        if first != len(self.words) or next(slots, None) is not None:
            raise ValueError(f"{first} words placed of {len(self.words)}")
        return replace(self, units=tuple(units))

    def cues(self) -> list[Cue]:
        """The result: each slot with its words on the reference cue's lines, each kept line as it was. A slot left
        without words lends its time to the slot before it, or else after it, given to the same line; one with neither
        is dropped."""
        found: list[Cue] = []
        extends = False  # the last cue found is a slot's, which the next slot of its line may lengthen
        lent: float | None = None  # the start empty slots leave to the next slot of their line
        for index, unit in enumerate(self.units):
            if unit.slot is None:
                found.append(Cue(unit.start, unit.end, unit.text, unit.style))
                extends, lent = False, None
            elif unit.count == 0:
                if unit.joined and extends:
                    found[-1] = replace(found[-1], end=max(found[-1].end, unit.end))
                elif index + 1 < len(self.units) and self.units[index + 1].joined:
                    lent, extends = unit.start if lent is None else lent, False
                else:
                    lent, extends = None, False
            else:
                words = self.words[unit.first : unit.first + unit.count]
                lines = self.reference[unit.slot].text.count("\n") + 1
                start = min(unit.start, lent) if lent is not None and unit.joined else unit.start
                found.append(
                    Cue(start, unit.end, self.carry[unit.first] + _lines(words, lines, self.tuning), unit.style)
                )
                extends, lent = True, None
        return found


def by_timing(lines: Sequence[Cue], reference: Sequence[Cue], tuning: Tuning = Tuning()) -> Layout:
    """The words of `lines` given to the cues of `reference` they are said over."""
    refs = tuple(sorted((cue for cue in reference if cue.end > cue.start), key=lambda cue: (cue.start, cue.end)))
    words: list[str] = []
    carry: list[str] = []
    units: list[Unit] = []
    floor = 0  # the first reference cue a line may still be given; the last one given may be shared
    given = -1  # the last reference cue given words
    for line in lines:
        tokens = _tokens(line.text)
        if not tokens:
            continue  # a line of no words, only markup or nothing, has nothing to move
        span = _span(line, refs, tuning.smallest_overlap)
        # A line said only over cues an earlier line was given past (lines out of order, or overlapping speakers) keeps
        # its own timing rather than taking a cue it is not said over.
        span = (max(span[0], floor), span[1]) if span is not None and span[1] >= floor else None
        if span is None:
            units.append(Unit(line.start, line.end, len(words), len(tokens), None, line.style, line.text))
            words += [word for word, _ in tokens]
            carry += [mark for _, mark in tokens]
            # The kept line lies between: the next line starts after the last cue given so far.
            floor = given + 1
            continue
        low, high = span
        weights = [_overlap(line, refs[index]) for index in range(low, high + 1)]
        counts = _cut([word for word, _ in tokens], weights, PULLS[tuning.punctuation])
        first = len(words)
        for offset, (index, count) in enumerate(zip(range(low, high + 1), counts, strict=True)):
            if units and units[-1].slot == index:
                units[-1] = replace(units[-1], count=units[-1].count + count)
            else:
                ref = refs[index]
                units.append(Unit(ref.start, ref.end, first, count, index, line.style, joined=offset > 0))
            first += count
        words += [word for word, _ in tokens]
        carry += [mark for _, mark in tokens]
        floor = given = high
    return Layout(tuple(words), tuple(carry), tuple(units), refs, tuning)


def plain_words(text: str) -> list[str]:
    """The words of a cue's text without its markup: what re-split must keep, each once and in order."""
    return [word for word in (_OVERRIDE.sub("", token) for token in text.split()) if word]


def _span(line: Cue, refs: Sequence[Cue], smallest: float) -> tuple[int, int] | None:
    """The first and last reference cue the line is said over; None where it overlaps none."""
    overlaps = [(index, amount) for index, ref in enumerate(refs) if (amount := _overlap(line, ref)) > 0]
    if not overlaps:
        return None
    said = [
        index
        for index, amount in overlaps
        if amount >= min(smallest, min(line.end - line.start, refs[index].end - refs[index].start) / 2)
    ]
    if not said:
        said = [max(overlaps, key=lambda found: found[1])[0]]
    return min(said), max(said)


def _overlap(a: Cue, b: Cue) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def _cut(words: Sequence[str], weights: Sequence[float], pull: float = 1.0) -> list[int]:
    """How many of the words go to each cue: in proportion to its weight by length of text, each cut moved to a
    nearby punctuation mark or speaker. The first cue always gets a word; the others do while there are enough."""
    pieces, total = len(weights), len(words)
    if pieces == 1:
        return [total]
    weights = list(weights) if sum(weights) > 0 else [1.0] * pieces
    lengths = [len(word) + 1 for word in plain_words(" ".join(words))] if total else []
    before = [0, *accumulate(lengths)]
    chars = before[-1] or 1
    shares = list(accumulate(weights))
    cuts, previous = [], 0
    for piece in range(1, pieces):
        target = chars * shares[piece - 1] / shares[-1]
        if total >= pieces:
            low, high = previous + 1, total - (pieces - piece)
        else:
            low, high = (max(previous, 1), total) if piece == 1 else (previous, total)
        low = min(low, high)
        best = min(
            range(low, high + 1),
            key=lambda at: (abs(before[at] - target) / chars - pull * _bonus(words, at), abs(before[at] - target)),
        )
        cuts.append(best)
        previous = best
    return [b - a for a, b in zip([0, *cuts], [*cuts, total], strict=True)]


def _bonus(words: Sequence[str], at: int) -> float:
    """What a cut before word `at` gains from the punctuation around it."""
    if at <= 0 or at >= len(words):
        return 0.0
    if (following := plain_words(words[at])) and following[0].startswith("-"):
        return _SPEAKER
    ending = "".join(plain_words(words[at - 1])).rstrip(_CLOSING)
    if ending.endswith((".", "!", "?", "…")):
        return _STRONG
    if ending.endswith((",", ";", ":")):
        return _WEAK
    return 0.0


def _tokens(text: str) -> list[tuple[str, str]]:
    """The words of a line, each with the markup a cue starting at it opens. Markup standing apart from any word goes
    with the next word, or the last one at the end, so every word cut keeps it."""
    tokens: list[str] = []
    waiting = ""
    for token in text.split():
        if not _OVERRIDE.sub("", token):
            waiting += token
        else:
            tokens.append(waiting + token)
            waiting = ""
    if waiting and tokens:
        tokens[-1] += waiting
    found: list[tuple[str, str]] = []
    flags: dict[str, bool] = {}
    position = ""
    for index, token in enumerate(tokens):
        opened = "".join(f"\\{flag}1" for flag, on in sorted(flags.items()) if on)
        mark = "{" + position + opened + "}" if index and (position or opened) else ""
        found.append((token, mark))
        for block in _OVERRIDE.findall(token):
            for tag in _TAG.finditer(block):
                if tag.group(1) is not None:
                    position = f"\\an{tag.group(1)}"
                else:
                    flags[tag.group(2)] = tag.group(3) != "0"
    return found


def _lines(words: Sequence[str], wanted: int, tuning: Tuning) -> str:
    """The words on the lines of a reference cue that has `wanted`: one line per speaker where the text starts with a
    speaker's dash, else two balanced lines for a long text on a cue of two, else one."""
    plain = [" ".join(plain_words(word)) for word in words]
    if len(words) > 1 and plain[0].startswith("-"):
        starts = [index for index in range(1, len(words)) if plain[index].startswith("-")]
        if starts:
            bounds = [0, *starts, len(words)]
            return "\n".join(" ".join(words[a:b]) for a, b in pairwise(bounds))
    length = sum(len(word) for word in plain) + len(plain) - 1
    if len(words) < 2 or not (length > tuning.longest_line or (wanted > 1 and length > tuning.two_lines_from)):
        return " ".join(words)
    before = [0, *accumulate(len(word) + 1 for word in plain)]
    at = min(range(1, len(words)), key=lambda cut: abs(before[cut] - (length + 1 - before[cut])))
    return " ".join(words[:at]) + "\n" + " ".join(words[at:])
