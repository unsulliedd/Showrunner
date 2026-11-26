"""The Lines panel beside the Subtitles place: the selected file's subtitle, one line per cue, with what the chosen
cleanup does to it marked live: a dropped line struck, a changed one shown with its new text, each with the rule that
did it. It reads a paired file as it is now; a text track inside the video is taken out in the background the first
time it is shown, and kept for as long as the video is as it was."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from showrunner.app.dependencies.service import programs_from
from showrunner.app.jobs.hashing import stamp
from showrunner.app.library.loader import BackgroundJob
from showrunner.app.rules import RULES, RuleStore
from showrunner.app.rules.effect import Effect, cues_effect, file_effect
from showrunner.core.cue import Cue, read_cues
from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.naming.names import codec_display
from showrunner.core.track import ObjectAudio, Track
from showrunner.stages.subtitles import FinishedSubtitle, StepKind, SubtitlePlan
from showrunner.stages.subtitles.read import track_cues
from showrunner.tools.cleanit import CueResult, RuleBook
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.review import ai_model, missing_phases, track_text
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


@dataclass(frozen=True, slots=True)
class Shown:
    """One subtitle of a file the panel can show: a paired file, or a text track inside the video."""

    label: str
    name: str
    language: Language | None
    path: Path | None = None  # a paired file
    track: Track | None = None  # a track of the video

    def is_finished(self, finished: FinishedSubtitle) -> bool:
        """Whether the plan's finished subtitle is made of this one."""
        if self.path is not None:
            return finished.paired is not None and finished.paired.path == self.path
        return finished.track is not None and finished.track == self.track


def shown_in(item: MediaItem) -> list[Shown]:
    """The subtitles of the file: its paired files, then its text tracks."""
    found = [Shown(code(s.language), s.path.name, s.language, path=s.path) for s in item.subtitles]
    found += [
        Shown(f"{code(t.language)} {codec_display(t.codec, ObjectAudio.NONE)}", track_text(t), t.language, track=t)
        for t in item.file.subtitle_tracks
        if t.subtitle is not None and t.subtitle.text_based
    ]
    return found


class LinesPanel(QObject):
    lines_changed = Signal()
    track_read = Signal()  # a text track of a video was taken out, so it can be shown and tested

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
        # The lines of the text tracks taken out so far, by video and track; None for one that could not be read.
        self._tracks: dict[tuple[Any, ...], list[Cue] | None] = {}
        self._reading: set[tuple[Any, ...]] = set()
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
        self._current()  # settles which file the index is of
        self._index = index
        self._follow()

    def loaded(self) -> tuple[list[Cue], Language | None, str] | None:
        """The cues of the subtitle now shown, as it is, with its language and name: what the rule editor tests
        against. A track of the video is asked for here, so the editor can use it once it is read."""
        found = self._current()
        if found is None:
            return None
        item, shown = found
        cues = self._cues(item, shown)
        return (cues, shown.language, shown.name) if cues is not None else None

    def _cues(self, item: MediaItem, shown: Shown) -> list[Cue] | None:
        """The lines of a subtitle, or None when they are not here (yet): a paired file is read now, a track of the
        video in the background."""
        if shown.path is not None:
            try:
                return read_cues(shown.path, shown.language)
            except (OSError, ValueError):
                return None
        assert shown.track is not None
        try:
            key = (item.file.path, stamp(item.file.path), shown.track.id)
        except OSError:
            return None
        if key not in self._tracks and key not in self._reading:
            self._read_track(key, item.file.path, shown)
        return self._tracks.get(key)

    def _read_track(self, key: tuple[Any, ...], video: Path, shown: Shown) -> None:
        extractor = programs_from(self._workspace.statuses or {}).mkvextract
        assert shown.track is not None
        if extractor is None:
            self._tracks[key] = None
            return
        track, language = shown.track, shown.language
        self._reading.add(key)
        job = BackgroundJob(lambda: track_cues(extractor, video, track, language))
        job.finished.connect(lambda cues: self._on_track(key, cues))
        job.failed.connect(lambda _error: self._on_track(key, None))
        job.start()

    def _on_track(self, key: tuple[Any, ...], cues: object) -> None:
        self._reading.discard(key)
        self._tracks[key] = cues if isinstance(cues, list) else None
        self._built = None
        self._follow()
        self.track_read.emit()

    def _current(self) -> tuple[MediaItem, Shown] | None:
        item = self._workspace.focus or (self._workspace.items[0] if self._workspace.items else None)
        if item is None:
            return None
        found = shown_in(item)
        if not found:
            return None
        if str(item.file.path) != self._path:
            self._path, self._index = str(item.file.path), 0
        return item, found[min(self._index, len(found) - 1)]

    def _sets(self, item: MediaItem, shown: Shown) -> tuple[tuple[str, ...], str]:
        """The rule sets the plan cleans this subtitle with, and why it cleans it with none: a paired file is not
        added, or other work it needs cannot run in this version."""
        file = next((f for f in self._workspace.current_files() if f.item.file.path == item.file.path), None)
        stage = file.plan_for(STAGE) if file is not None else None
        if stage is None or not isinstance(stage.plan, SubtitlePlan):
            return (), tr("lines.not_cleaned")
        for finished in stage.plan.finished:
            if shown.is_finished(finished):
                return next((s.sets for s in finished.steps if s.kind is StepKind.CLEAN), ()), tr("lines.not_cleaned")
        if any(s.path == shown.path for s in stage.plan.not_added):
            return (), tr("lines.not_added")
        for finished in stage.plan.left_out:
            if shown.is_finished(finished):
                return (), tr("lines.left_out", reason=unavailable(missing_phases(finished)[0], ai_model(finished)))
        return (), tr("lines.not_cleaned")

    def _build(self) -> dict[str, Any]:
        found = self._current()
        if found is None:
            return {"empty": tr("lines.none"), "languages": [], "rows": []}
        item, shown = found
        every = shown_in(item)
        languages = [{"label": s.label, "name": s.name, "current": s == shown} for s in every]
        names, why = self._sets(item, shown)
        book = self._rules.book()
        effect = self._effect(item, shown, names, book)
        if effect is None:
            return {"empty": self._missing(item, shown), "languages": languages, "rows": []}
        return {
            "empty": "",
            "file": shown.name,
            "languages": languages,
            "index": every.index(shown),
            "sets": tr("common.list_separator").join(set_label(n) for n in names),
            "summary": self._summary(effect) if names else why,
            "rows": [_row(result) for result in effect.results[:_SHOWN]],
            "more": max(0, len(effect.results) - _SHOWN),
        }

    def _missing(self, item: MediaItem, shown: Shown) -> str:
        """Why a subtitle shows no lines: its track is being read out of the video, cannot be, or its file is no
        subtitle."""
        if shown.track is None:
            return tr("lines.unreadable", file=shown.name)
        try:
            reading = (item.file.path, stamp(item.file.path), shown.track.id) in self._reading
        except OSError:
            reading = False
        return tr("lines.reading", track=shown.name) if reading else tr("lines.track_unreadable", track=shown.name)

    def _effect(self, item: MediaItem, shown: Shown, names: tuple[str, ...], book: RuleBook) -> Effect | None:
        source = shown.path if shown.path is not None else item.file.path
        try:
            key = (source, stamp(source), shown.track.id if shown.track else None, names)
            key += tuple(s.fingerprint for s in book.known(names))
        except OSError:
            return None
        if self._read is not None and self._read[0] == key:
            return self._read[1]
        if shown.path is not None:
            found = file_effect(shown.path, shown.language, names, book)
        else:
            cues = self._cues(item, shown)
            if cues is None:
                return None
            found = cues_effect(cues, shown.language, names, book)
        self._read = (key, found)
        return found

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
