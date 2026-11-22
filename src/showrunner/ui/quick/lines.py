"""The Lines panel beside the Subtitles place: the selected file's subtitle, one line per cue, with what the chosen
cleanup does to it marked live: a dropped line struck, a changed one shown with its new text, each with the rule that
did it. It reads the paired file as it is now; a subtitle that exists only inside the video is not read yet."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from showrunner.app.jobs.hashing import stamp
from showrunner.app.rules import RULES, RuleStore
from showrunner.app.rules.effect import Effect, file_effect
from showrunner.core.cue import Cue, read_cues
from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.stages.subtitles import StepKind, SubtitlePlan
from showrunner.tools.cleanit import CueResult, RuleBook
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.review import missing_phases
from showrunner.ui.quick.subtitles import STAGE, set_label, unavailable
from showrunner.ui.quick.tracks import code
from showrunner.ui.quick.workspace import Workspace

# The lines drawn at most: a feature film has about two thousand, and a longer list is no longer read line by line.
_SHOWN = 3000


def clock(seconds: float) -> str:
    """`1:02:03.4`: the time a line starts, to a tenth of a second."""
    tenths = round(seconds * 10)
    hours, rest = divmod(tenths, 36000)
    minutes, rest = divmod(rest, 600)
    return f"{hours}:{minutes:02d}:{rest // 10:02d}.{rest % 10}"


def rule_label(name: str) -> str:
    """A rule's name without the set and language cleanit's own names carry in brackets."""
    return name.split("[", 1)[0]


class LinesPanel(QObject):
    lines_changed = Signal()

    def __init__(self, workspace: Workspace, rules: RuleStore = RULES, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._rules = rules
        self._index = 0  # which of the file's subtitles
        self._path = ""
        self._built: dict[str, Any] | None = None
        # The last file read with the rules that cleaned it: a long rule set takes seconds on a long subtitle, and the
        # panel is built again at every change the window makes.
        self._read: tuple[tuple[Any, ...], Effect | None] | None = None
        for signal in (workspace.rebuilt, workspace.plans_changed, workspace.batch_changed, workspace.place_shown):
            signal.connect(self._follow)

    @property
    def view(self) -> dict[str, Any]:
        if self._built is None:
            self._built = self._build()
        return self._built

    def _follow(self) -> None:
        # Nothing is read while the place is hidden: the panel is built when read.
        if self._workspace.place != "subtitles":
            self._built = None
            return
        built = self._build()
        if built != self._built:
            self._built = built
            self.lines_changed.emit()

    @Slot(int)
    def pick(self, index: int) -> None:
        self._index = index
        self._follow()

    def loaded(self) -> tuple[list[Cue], Language | None, str] | None:
        """The cues of the subtitle now shown, as the file has them, with its language and the file's name: what the
        rule editor tests against."""
        found = self._current()
        if found is None:
            return None
        _item, subtitle = found
        try:
            return read_cues(subtitle.path, subtitle.language), subtitle.language, subtitle.path.name
        except (OSError, ValueError):
            return None

    def _current(self) -> tuple[MediaItem, SubtitleFile] | None:
        item = self._workspace.focus or (self._workspace.items[0] if self._workspace.items else None)
        if item is None or not item.subtitles:
            return None
        if str(item.file.path) != self._path:
            self._path, self._index = str(item.file.path), 0
        return item, item.subtitles[min(self._index, len(item.subtitles) - 1)]

    def _sets(self, item: MediaItem, subtitle: SubtitleFile) -> tuple[tuple[str, ...], str]:
        """The rule sets the plan cleans this paired file with, and why it cleans it with none: the file is not added,
        or other work it needs cannot run in this version."""
        file = next((f for f in self._workspace.current_files() if f.item.file.path == item.file.path), None)
        stage = file.plan_for(STAGE) if file is not None else None
        if stage is None or not isinstance(stage.plan, SubtitlePlan):
            return (), tr("lines.not_cleaned")
        for finished in stage.plan.finished:
            if finished.paired is not None and finished.paired.path == subtitle.path:
                return next((s.sets for s in finished.steps if s.kind is StepKind.CLEAN), ()), tr("lines.not_cleaned")
        if any(s.path == subtitle.path for s in stage.plan.not_added):
            return (), tr("lines.not_added")
        for finished in stage.plan.left_out:
            if finished.paired is not None and finished.paired.path == subtitle.path:
                return (), tr("lines.left_out", reason=unavailable(missing_phases(finished)[0]))
        return (), tr("lines.not_cleaned")

    def _build(self) -> dict[str, Any]:
        found = self._current()
        if found is None:
            return {"empty": tr("lines.none"), "languages": [], "rows": []}
        item, subtitle = found
        names, why = self._sets(item, subtitle)
        book = self._rules.book()
        effect = self._effect(subtitle, names, book)
        languages = [
            {"label": code(s.language), "name": s.path.name, "current": s.path == subtitle.path} for s in item.subtitles
        ]
        if effect is None:
            return {"empty": tr("lines.unreadable", file=subtitle.path.name), "languages": languages, "rows": []}
        return {
            "empty": "",
            "file": subtitle.path.name,
            "languages": languages,
            "index": item.subtitles.index(subtitle),
            "sets": tr("common.list_separator").join(set_label(n) for n in names),
            "summary": self._summary(effect) if names else why,
            "rows": [_row(result) for result in effect.results[:_SHOWN]],
            "more": max(0, len(effect.results) - _SHOWN),
        }

    def _effect(self, subtitle: SubtitleFile, names: tuple[str, ...], book: RuleBook) -> Effect | None:
        try:
            key = (subtitle.path, stamp(subtitle.path), names, tuple(s.fingerprint for s in book.known(names)))
        except OSError:
            return None
        if self._read is None or self._read[0] != key:
            self._read = (key, file_effect(subtitle.path, subtitle.language, names, book))
        return self._read[1]

    @staticmethod
    def _summary(effect: Effect) -> str:
        return tr(
            "cleanup.count_short",
            dropped=tr_plural("cleanup.lines", effect.dropped),
            changed=tr_plural("cleanup.lines", effect.changed),
        )


def _row(result: CueResult) -> dict[str, Any]:
    state = "looped" if result.looped else "dropped" if result.dropped else "changed" if result.changed else "kept"
    return {
        "time": clock(result.cue.start),
        "text": result.cue.text.replace("\n", " ⏎ "),
        "after": (result.text or "").replace("\n", " ⏎ ") if state == "changed" else "",
        "state": state,
        "rule": ", ".join(dict.fromkeys(rule_label(r) for r in result.rules)),
    }
