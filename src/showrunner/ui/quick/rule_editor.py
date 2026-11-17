"""The editor of a hand-written track rule, behind the Rules panel: its draft, its problems and its form for QML.

The draft lives here and nothing reaches the batch's working copy before Save, so Cancel leaves the rule as it was.
Text fields are kept as typed and handed back unchanged, so a form that is rebuilt (a plan arriving, a pick toggled)
never moves the cursor of a field being typed in. QML draws what `form` holds and sends every change to a slot.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from showrunner.app.batches.choices import add_rule, replace_rule
from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.naming.names import codec_display
from showrunner.core.track import ObjectAudio, Track
from showrunner.stages.tracks import (
    NO_LANGUAGE,
    FlagShape,
    FlagTest,
    KindTest,
    RuleField,
    SourceTest,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
    check_rules,
    stand_in,
)
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.tracks import BatchView, rule_parts

# The tests on a track's flags, in the order the form lists them.
FLAG_TESTS = ("default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original")
# The flags a rule can give to the first track it keeps.
FLAG_ACTIONS = ("default", "forced")
# The fields that hold free text, and how long a channel count is.
TEXT_FIELDS = ("label", "languages", "codecs", "low", "high", "name")
MAX_CHANNEL_DIGITS = 2


def _split(text: str) -> list[str]:
    return [entry.strip() for entry in text.split(",") if entry.strip()]


def _count(text: str) -> int:
    return int(text) if text.isascii() and text.isdigit() else 0


def _same_language(entry: str, tag: str) -> bool:
    """Whether a typed entry names the language of `tag` (`tur` and `tr` do)."""
    if entry.strip().casefold() == tag.casefold():
        return True
    wanted, found = Language.parse(entry), Language.parse(tag)
    return wanted is not None and wanted == found


@dataclass(frozen=True, slots=True)
class Draft:
    """A rule on its way to being saved: the rule as the fields give it so far, and the fields' text as typed.
    `at` is the place of the rule being edited, `None` for a new one; `original` is that rule as it was opened."""

    rule: TrackRule
    languages: str = ""
    codecs: str = ""
    low: str = ""
    high: str = ""
    at: int | None = None
    original: TrackRule | None = None

    @classmethod
    def new(cls) -> Draft:
        return cls(TrackRule())

    @classmethod
    def of(cls, rule: TrackRule, at: int) -> Draft:
        match = rule.match
        return cls(
            rule,
            languages=", ".join(match.languages),
            codecs=", ".join(match.codecs),
            low=str(match.min_channels) if match.min_channels else "",
            high=str(match.max_channels) if match.max_channels else "",
            at=at,
            original=rule,
        )

    @property
    def match(self) -> TrackMatch:
        return self.rule.match

    def with_match(self, **changes: Any) -> Draft:
        return replace(self, rule=replace(self.rule, match=replace(self.match, **changes)))

    def with_text(self, field: str, text: str) -> Draft:
        if field == "label":
            return replace(self, rule=replace(self.rule, label=text))
        if field == "languages":
            return replace(self, languages=text).with_match(languages=_split(text))
        if field == "codecs":
            return replace(self, codecs=text).with_match(codecs=_split(text))
        if field == "low":
            return replace(self, low=text).with_match(min_channels=_count(text))
        if field == "high":
            return replace(self, high=text).with_match(max_channels=_count(text))
        return self.with_match(name=text)

    def with_kind(self, kind: KindTest) -> Draft:
        """Another kind. A test that cannot fit it is reset: only subtitles come from paired files, and only audio
        has channels, so such a test would leave the rule fitting nothing, out of sight."""
        draft = self.with_match(kind=kind)
        if kind in (KindTest.AUDIO, KindTest.VIDEO) and self.match.source is SourceTest.PAIRED:
            draft = draft.with_match(source=SourceTest.ANY)
        if kind in (KindTest.VIDEO, KindTest.SUBTITLE):
            draft = replace(draft, low="", high="").with_match(min_channels=0, max_channels=0)
        return draft

    def with_verdict(self, verdict: Verdict) -> Draft:
        """Another verdict. A dropped track takes no flag, so a drop leaves the flag actions off."""
        rule = replace(self.rule, verdict=verdict)
        if verdict is Verdict.DROP:
            rule = replace(rule, default=FlagShape.LEAVE, forced=FlagShape.LEAVE)
        return replace(self, rule=rule)

    def final(self) -> TrackRule:
        """The rule to store. An edited rule keeps what the form does not show: whether it is paused, and that it was
        written by hand."""
        base = self.original if self.original is not None else TrackRule()
        rule = self.rule
        return replace(
            base, label=rule.label, match=rule.match, verdict=rule.verdict, default=rule.default, forced=rule.forced
        )

    def paired_offered(self) -> bool:
        """Whether a file beside the video can be asked for: only a subtitle comes from one. A rule that already asks
        for it stays visible, so that its problem can be fixed."""
        return self.match.kind in (KindTest.ANY, KindTest.SUBTITLE) or self.match.source is SourceTest.PAIRED


def problems(draft: Draft) -> dict[str, list[str]]:
    """The draft's problems worded, by the field they belong to; empty when it can be saved."""
    found: dict[str, list[str]] = {}
    for problem in check_rules(TracksOptions(rules=[draft.rule])):
        if problem.field is RuleField.LANGUAGES:
            text = tr("rules.editor.problem.language", entry=problem.detail)
        elif problem.field is RuleField.CHANNELS:
            text = tr("rules.editor.problem.channels")
        else:
            text = tr("rules.editor.problem.pattern", error=problem.detail)
        found.setdefault(problem.field.value, []).append(text)
    match = draft.match
    if match.source is SourceTest.PAIRED and match.kind in (KindTest.AUDIO, KindTest.VIDEO):
        found["source"] = [tr("rules.editor.problem.source")]
    return found


def _tracks(items: Sequence[MediaItem], kind: KindTest) -> list[Track]:
    """The tracks of the batch's files and the paired subtitle files beside them, of the kind a rule asks for."""
    tracks = [
        track
        for item in items
        for track in (*item.file.tracks, *(stand_in(s, n) for n, s in enumerate(item.subtitles)))
    ]
    return [t for t in tracks if kind is KindTest.ANY or t.kind.value == kind.value]


def language_picks(items: Sequence[MediaItem], kind: KindTest, typed: Sequence[str]) -> list[dict[str, Any]]:
    """The languages the batch's tracks have, each as an entry a rule can take, in the order first seen."""
    tags = dict.fromkeys(t.language.ietf if t.language else NO_LANGUAGE for t in _tracks(items, kind))
    picks = []
    for tag in tags:
        language = Language.parse(tag) if tag != NO_LANGUAGE else None
        name = language.name if language else tr("tracks.no_language")
        picks.append({"value": tag, "text": name, "on": any(_same_language(entry, tag) for entry in typed)})
    return picks


def codec_picks(items: Sequence[MediaItem], kind: KindTest, typed: Sequence[str]) -> list[dict[str, Any]]:
    """The codecs the batch's tracks have, by the name a rule can use; one entry for codecs that share a name."""
    names = {entry.casefold() for entry in typed}
    found: dict[str, set[str]] = {}
    for track in _tracks(items, kind):
        if track.codec:
            found.setdefault(codec_display(track.codec, ObjectAudio.NONE), set()).add(track.codec.casefold())
    return [
        {
            "value": name,
            "text": name,
            # A codec may be typed by its name or by a Matroska ID; taking the pick out removes either.
            "ids": sorted(ids),
            "on": name.casefold() in names or not names.isdisjoint(ids),
        }
        for name, ids in found.items()
    ]


def toggled(text: str, value: str, on: bool, same: Callable[[str], bool]) -> str:
    """The comma list `text` with the entries `same` accepts taken out when `on`, else `value` added at the end."""
    entries = _split(text)
    if on:
        return ", ".join(entry for entry in entries if not same(entry))
    return ", ".join([*entries, value])


class RuleEditor(QObject):
    """`app.rule_editor`: add a hand-written rule or edit one. A rule a choice on a track wrote is not edited here,
    since undoing the choice on its track is what removes it."""

    changed = Signal()

    def __init__(
        self,
        options: Callable[[], TracksOptions | None],
        apply: Callable[[TracksOptions], None],
        locked: Callable[[], bool],
        items: Callable[[], Sequence[MediaItem]],
        view: Callable[[], BatchView | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._options, self._apply, self._locked, self._items, self._view = options, apply, locked, items, view
        self._draft: Draft | None = None
        self._form: dict[str, Any] = {"open": False}
        self._picks: dict[str, list[dict[str, Any]]] = {}

    # What QML reads

    @Property("QVariantMap", notify=changed)
    def form(self) -> dict[str, Any]:
        return self._form

    @Property("QVariantMap", constant=True)
    def options(self) -> dict[str, Any]:
        """What never changes while the editor is open: the lists of choices, worded."""

        def choices(keys: Sequence[str], prefix: str) -> list[dict[str, str]]:
            return [{"key": key, "label": tr(f"{prefix}.{key}")} for key in keys]

        return {
            "kinds": choices([k.value for k in KindTest], "rules.editor.kind"),
            "tests": choices([t.value for t in FlagTest], "rules.editor.test"),
            "flags": [{"key": flag, "label": tr(f"rules.editor.flag.{flag}")} for flag in FLAG_TESTS],
            "verdicts": choices([v.value for v in Verdict], "rules.editor.verdict"),
            "shapes": choices([s.value for s in FlagShape], "rules.editor.shape"),
            "actions": [{"key": flag, "label": tr(f"rules.editor.action.{flag}")} for flag in FLAG_ACTIONS],
            "sources": choices([SourceTest.ANY.value, SourceTest.EMBEDDED.value], "rules.editor.source"),
            "sources_with_paired": choices([s.value for s in SourceTest], "rules.editor.source"),
            "digits": MAX_CHANNEL_DIGITS,
        }

    # Opening and closing

    @Slot()
    def open_new(self) -> None:
        if self._options() is not None:
            self._draft = Draft.new()
            self._rebuild()

    @Slot(int)
    def open_rule(self, index: int) -> None:
        """Open the hand-written rule at `index`; a rule a choice wrote is refused."""
        options = self._options()
        if options is None or not 0 <= index < len(options.rules) or options.rules[index].from_choice:
            return
        self._draft = Draft.of(options.rules[index], index)
        self._rebuild()

    @Slot()
    def cancel(self) -> None:
        self.close()

    def close(self) -> None:
        if self._draft is not None:
            self._draft = None
            self._rebuild()

    @Slot(result=bool)
    def save(self) -> bool:
        """Write the rule to the batch's working copy: a new one at the end of the list, an edited one in its place.
        Nothing is written, and the editor stays open, while the rule has a problem or the batch is locked. Returns
        whether the rule was saved."""
        draft, options = self._draft, self._options()
        if draft is None or options is None or problems(draft) or self._locked():
            return False
        rule = draft.final()
        if draft.at is None:
            self._apply(add_rule(options, rule))
        else:
            at = self._where(options, draft)
            if at is None:
                self.close()  # the rule was deleted meanwhile: there is nothing left to write over
                return False
            if rule != options.rules[at]:
                self._apply(replace_rule(options, at, rule))
        self.close()
        return True

    @staticmethod
    def _where(options: TracksOptions, draft: Draft) -> int | None:
        """The place of the rule being edited as the list is now: a choice made meanwhile puts its rule ahead of the
        hand-written ones, so the place it was opened at may hold another rule. `None` when the rule is gone."""
        assert draft.at is not None
        assert draft.original is not None
        if draft.at < len(options.rules) and options.rules[draft.at] == draft.original:
            return draft.at
        return options.rules.index(draft.original) if draft.original in options.rules else None

    # Changing the draft

    def _change(self, make: Callable[[Draft], Draft]) -> None:
        if self._draft is not None:
            self._draft = make(self._draft)
            self._rebuild()

    @Slot(str, str)
    def set_text(self, field: str, text: str) -> None:
        if field in TEXT_FIELDS:
            self._change(lambda d: d.with_text(field, text))

    @Slot(str)
    def set_kind(self, kind: str) -> None:
        if kind in KindTest:
            self._change(lambda d: d.with_kind(KindTest(kind)))

    @Slot(str)
    def set_source(self, source: str) -> None:
        if source in SourceTest:
            self._change(lambda d: d.with_match(source=SourceTest(source)))

    @Slot(str, str)
    def set_test(self, flag: str, test: str) -> None:
        if flag in FLAG_TESTS and test in FlagTest:
            self._change(lambda d: d.with_match(**{flag: FlagTest(test)}))

    @Slot(bool)
    def set_regex(self, on: bool) -> None:
        self._change(lambda d: d.with_match(name_is_regex=on))

    @Slot(str)
    def set_verdict(self, verdict: str) -> None:
        if verdict in Verdict:
            self._change(lambda d: d.with_verdict(Verdict(verdict)))

    @Slot(str, str)
    def set_action(self, flag: str, shape: str) -> None:
        if flag in FLAG_ACTIONS and shape in FlagShape:
            self._change(lambda d: replace(d, rule=replace(d.rule, **{flag: FlagShape(shape)})))

    @Slot(str, int)
    def toggle_pick(self, field: str, index: int) -> None:
        """Take the language or codec at `index` of the batch's list into the field, or out of it."""
        picks = self._picks.get(field, [])
        if field in ("languages", "codecs") and 0 <= index < len(picks):
            pick = picks[index]
            value = pick["value"]
            if field == "languages":

                def same(entry: str) -> bool:
                    return _same_language(entry, value)

            else:

                def same(entry: str) -> bool:
                    return entry.casefold() == value.casefold() or entry.casefold() in pick["ids"]

            self._change(lambda d: d.with_text(field, toggled(getattr(d, field), value, pick["on"], same)))

    # The form

    def refresh(self) -> None:
        """What the form reads from the batch (the files it fits, whether it is locked) may have changed."""
        if self._draft is not None:
            self._rebuild()

    def _rebuild(self) -> None:
        self._form = self._build()
        self.changed.emit()

    def _build(self) -> dict[str, Any]:
        draft, options = self._draft, self._options()
        if draft is None or options is None:
            self._picks = {}
            # The fields keep a form to read while the view that holds them is taken down.
            return {**self._form, "open": False}
        match = draft.match
        found = problems(draft)
        locked = self._locked()
        items = self._items()
        self._picks = {
            "languages": language_picks(items, match.kind, match.languages),
            "codecs": codec_picks(items, match.kind, match.codecs),
        }
        view = self._view()
        above = options.rules[: draft.at] if draft.at is not None else options.rules
        rule = draft.rule
        return {
            "open": True,
            "new": draft.at is None,
            "title": tr("rules.editor.new") if draft.at is None else tr("rules.editor.edit", number=draft.at + 1),
            "label": rule.label,
            "kind": match.kind.value,
            "languages": draft.languages,
            "language_names": ", ".join(self._names(match.languages)),
            "language_picks": self._picks["languages"],
            "codecs": draft.codecs,
            "codec_picks": self._picks["codecs"],
            "channels_shown": match.kind in (KindTest.ANY, KindTest.AUDIO),
            "low": draft.low,
            "high": draft.high,
            "name": match.name,
            "regex": match.name_is_regex,
            "tests": {flag: getattr(match, flag).value for flag in FLAG_TESTS},
            "paired_offered": draft.paired_offered(),
            "source": match.source.value,
            "verdict": rule.verdict.value,
            "flags_shown": rule.verdict is not Verdict.DROP,
            "default": rule.default.value,
            "forced": rule.forced.value,
            "parts": rule_parts(rule, None, above),
            "fits": tr_plural("tracks.rule.fits", view.fits(rule)) if view is not None else "",
            "problems": found,
            # Why Save cannot be pressed, for a problem that is further down the form than the screen shows.
            "note": tr("rules.editor.locked") if locked else tr("rules.editor.problems") if found else "",
            "note_tone": "change" if locked else "drop",
            "can_save": not found and not locked,
        }

    @staticmethod
    def _names(tags: Sequence[str]) -> list[str]:
        """The names of the languages typed that are languages, so a typo shows by what is missing."""
        names = []
        for tag in tags:
            language = Language.parse(tag)
            if tag.casefold() == NO_LANGUAGE:
                names.append(tr("tracks.no_language"))
            elif language is not None:
                names.append(language.name)
        return names
