"""The track choices of the open place, from Overview's chips, the Tracks strip and the Rules panel: keep or drop, the
default and forced flags, the language a track gets, a name's or a file's own choice, and the order of the rules and
tracks. Each ends in the open place's own track or metadata options."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject

from showrunner.app.batches.batch import BatchKey
from showrunner.app.batches.choices import (
    NO_CHOICE,
    TrackChoice,
    TrackSignature,
    add_paired,
    choice_of,
    move_rule,
    move_track,
    named,
    pause_rule,
)
from showrunner.app.jobs.blocked import blocked_stages
from showrunner.core.language import Language
from showrunner.stages.tracks import NO_LANGUAGE, TracksOptions, Verdict
from showrunner.tools.dependencies.detect import State
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.quick.languages import LanguagePicker
from showrunner.ui.quick.tracks import columns
from showrunner.ui.quick.workspace import Workspace


class Choices(QObject):
    def __init__(self, workspace: Workspace, picker: LanguagePicker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._picker = picker
        self._picking: TrackSignature | None = None  # the chip the language picker is open for
        picker.applied.connect(self._on_language_picked)

    def track_name_rows(self, column: int) -> list[dict[str, Any]]:
        """The lines of a chip's ▾ list, a clickable one per name where the chip's tracks carry several (see
        `BatchView.name_rows`), built when the list opens and again with each plan."""
        view = self._workspace.view
        return view.name_rows(column) if view is not None else []

    def toggle_name(self, column: int, name: str) -> None:
        """A click on one name of a chip's list: drop the tracks with that name, keep them when they are dropped, and
        take the choice back when it is already a drop, as for the chip. It is a rule ahead of the chip's own choice,
        so the chip's other names stay as the chip has them."""
        workspace = self._workspace
        found = workspace.column(column)
        if found is None or workspace.view is None or workspace.key is None:
            return
        col, _header = found
        row = next((r for r in workspace.view.name_rows(column) if r["clickable"] and r["name"] == name), None)
        if row is None:
            return
        signature = named(col.signature, name)
        if choice_of(workspace.tracks(), signature).verdict is Verdict.DROP:
            verdict = Verdict.PASS
        else:
            verdict = Verdict.KEEP if row["dropped"] else Verdict.DROP
        workspace.set_tracks(workspace.batches.with_choice(workspace.key, signature, TrackChoice(verdict), lead=True))

    def toggle_file_track(self, column: int, path: str) -> None:
        """A click on the line of one file's track in a chip's list: drop that file's track, keep it when it is
        dropped, and give the choice back to the place above when the file's own choice was the drop. The choice is
        made at the file's own place and overrides what the file receives, so the other files stay as they are."""
        workspace = self._workspace
        found = workspace.column(column)
        item = workspace.file_item(path)
        if found is None or workspace.view is None or workspace.key is None or item is None:
            return
        col, _header = found
        key = BatchKey.file(item).in_show(workspace.key)
        signature = col.signature
        choice = choice_of(workspace.batches.profile(key).for_stage("tracks"), signature)
        received = workspace.batches.received_choice(key, signature)
        if choice.verdict is Verdict.DROP:
            # Undoing a drop: what the place above says, or a keep where that is a drop as well.
            chosen = (
                TrackChoice(Verdict.KEEP, language=choice.language) if received.verdict is Verdict.DROP else received
            )
        elif workspace.view.cells(item)[column]["state"] == "dropped":
            chosen = TrackChoice(
                Verdict.KEEP, choice.default, choice.forced, choice.language
            )  # a written rule drops it
        else:
            chosen = TrackChoice(Verdict.DROP, language=choice.language)
        workspace.set_options("tracks", workspace.batches.with_choice(key, signature, chosen), key)

    def track_missing(self, column: int) -> str:
        """The line naming the files that lack a chip's or matrix column's track; empty when every file has it."""
        view = self._workspace.view
        return view.missing(column) if view is not None else ""

    def track_held(self, column: int) -> str:
        """The line naming the files that keep a dropped chip's track and why; empty when the plan drops it where it
        can."""
        view = self._workspace.view
        return view.held_note(column) if view is not None else ""

    def toggle_keep(self, column: int) -> None:
        """A click on a chip or a column's state: drop what stays, keep what is dropped, add a paired file."""
        workspace = self._workspace
        found = workspace.column(column)
        if found is None:
            return
        col, header = found
        assert workspace.key is not None
        if col.paired is not None:
            added = header["state"] == "added"
            options = (
                workspace.batches.with_choice(workspace.key, col.signature, NO_CHOICE)
                if added
                else workspace.own_tracks()
            )
            workspace.set_tracks(add_paired(options, col.paired, not added))
            return
        choice = choice_of(workspace.tracks(), col.signature)
        if choice.verdict is Verdict.DROP:
            # Undoing this choice's drop gives the track back, also when a refused plan shows the track kept.
            verdict = Verdict.PASS
        elif header["state"] == "dropped":
            verdict = Verdict.KEEP  # a hand-written rule drops it
        else:
            verdict = Verdict.DROP
        chosen = TrackChoice(verdict, choice.default, choice.forced, choice.language)
        workspace.set_tracks(workspace.batches.with_choice(workspace.key, col.signature, chosen))

    def toggle_flag(self, column: int, flag: str) -> None:
        """The D (default) or F (forced) of a chip, card or column; a flag on a paired file adds the file."""
        workspace = self._workspace
        found = workspace.column(column)
        if found is None or flag not in ("default", "forced"):
            return
        col, header = found
        assert workspace.key is not None
        choice = choice_of(workspace.tracks(), col.signature)
        on = not getattr(choice, flag)
        flags = {"default": choice.default, "forced": choice.forced, flag: on}
        if on:
            verdict = Verdict.KEEP
        elif choice.verdict is Verdict.KEEP and not any(flags.values()):
            verdict = Verdict.PASS  # a keep that only carried the flag goes with it
        else:
            verdict = choice.verdict
        options = workspace.batches.with_choice(
            workspace.key, col.signature, TrackChoice(verdict, **flags, language=choice.language)
        )
        if col.paired is not None and header["state"] != "added":
            options = add_paired(options, col.paired, True)
        workspace.set_tracks(options)

    def restore(self, column: int) -> None:
        """Undo every choice the batch made on a column: its rule goes, and a paired file is added or not as the
        batch receives it (not at all in a show or the Movies group)."""
        workspace = self._workspace
        found = workspace.column(column)
        if found is None or workspace.key is None:
            return
        col, _header = found
        received = workspace.batches.received(workspace.key)
        given_choice = workspace.batches.received_choice(workspace.key, col.signature)
        options = workspace.batches.with_choice(workspace.key, col.signature, given_choice)
        if col.paired is not None:
            given = received is not None and col.paired in received.for_stage("tracks").add_paired
            options = add_paired(options, col.paired, given)
        workspace.set_tracks(options)

    # The rule methods take places in the batch's own rules, which lead the Rules panel; the rules it receives from
    # above follow them there and are changed where they were set.

    def move_rule(self, source: int, target: int) -> None:
        workspace = self._workspace
        if workspace.key is not None and 0 <= source < len(workspace.own_tracks().rules) and source != target:
            workspace.set_tracks(move_rule(workspace.own_tracks(), source, target))

    def move_track(self, column: int, target: int) -> int:
        """Move a matrix column or a movie card to `target`, kept among the columns of its kind: the tracks of the new
        files take that order. Returns where the column is now, so the keyboard focus can follow it."""
        workspace = self._workspace
        view = workspace.view
        if view is None or workspace.key is None or not 0 <= column < len(view.cols):
            return column
        moved = view.cols[column]
        shown = [c.signature for c in view.cols]
        natural = [c.signature for c in columns(view.items, view.grouping)]
        options = move_track(workspace.own_tracks(), shown, natural, column, target)
        if options.order != workspace.tracks().order:
            workspace.set_tracks(options)
        return workspace.view.cols.index(moved) if workspace.view is not None else column

    def pause_rule(self, index: int, paused: bool) -> None:
        workspace = self._workspace
        if workspace.key is not None and 0 <= index < len(workspace.own_tracks().rules):
            workspace.set_tracks(pause_rule(workspace.own_tracks(), index, paused))

    def remove_rule(self, index: int) -> None:
        """Delete a hand-written rule. A rule a choice wrote goes by undoing the choice on its track instead."""
        workspace = self._workspace
        own = workspace.own_tracks() if workspace.key is not None else TracksOptions()
        if 0 <= index < len(own.rules) and not own.rules[index].from_choice:
            workspace.set_tracks(replace(own, rules=own.rules[:index] + own.rules[index + 1 :]))

    # Languages

    def _batch_languages(self) -> set[str]:
        """The 3-letter codes of the languages the selected batch's tracks have, which the picker lists first."""
        view = self._workspace.view
        found = (Language.parse(c.signature.language) for c in (view.cols if view else ()))
        return {language.alpha3 for language in found if language is not None}

    def pick_language(self, column: int) -> None:
        """Open the language picker for a chip, card or column: the language its tracks get, as a rule like the
        other choices on it."""
        workspace = self._workspace
        found = workspace.column(column)
        if found is None or workspace.view is None or workspace.locked:
            return
        col, header = found
        choice = choice_of(workspace.tracks(), col.signature)
        tag = choice.language or (col.signature.language if col.signature.language != NO_LANGUAGE else "")
        self._picking = col.signature
        what = f"{header['code']} {header['title']}".strip()
        title = tr("language.title.chip", what=what)
        self._picker.begin("chip", title, tag, self._batch_languages(), clearable=bool(choice.language))

    def pick_untagged_language(self) -> None:
        """Open the language picker for the tracks that have no language, as the Names place asks."""
        workspace = self._workspace
        if workspace.key is None or workspace.locked:
            return
        tag = workspace.batches.profile(workspace.key).for_stage("metadata").untagged_language
        self._picking = None
        self._picker.begin("untagged", tr("names.untagged"), tag, self._batch_languages(), clearable=bool(tag))

    def _on_language_picked(self, target: str, tag: str) -> None:
        workspace = self._workspace
        if target == "untagged":
            self.set_untagged_language(tag)
        elif target == "chip" and self._picking is not None and workspace.key is not None and not workspace.locked:
            choice = choice_of(workspace.tracks(), self._picking)
            workspace.set_tracks(
                workspace.batches.with_choice(workspace.key, self._picking, replace(choice, language=tag))
            )

    @property
    def untagged(self) -> dict[str, str]:
        """The language given to tracks that have none, in the selected batch, and why it cannot be used."""
        workspace = self._workspace
        if workspace.key is None:
            return {"value": "", "label": tr("names.untagged_none"), "problem": ""}
        profile = workspace.batches.profile(workspace.key)
        block = blocked_stages(profile).get("metadata")
        bad = block.language if block is not None else ""
        value = profile.for_stage("metadata").untagged_language
        language = Language.parse(value) if value else None
        label = (
            tr("language.untagged_value", name=language.display, tag=language.ietf)
            if language is not None
            else value or tr("names.untagged_none")
        )
        return {
            "value": value,
            "label": label,
            "problem": tr("names.blocked.language", language=bad) if bad else "",
        }

    def set_untagged_language(self, text: str) -> None:
        workspace = self._workspace
        if workspace.key is None or workspace.locked:
            return
        metadata = workspace.batches.profile(workspace.key).for_stage("metadata")
        if text.strip() != metadata.untagged_language:
            workspace.set_options("metadata", replace(metadata, untagged_language=text.strip()))

    # Flags the names imply

    @property
    def write_implied_flags(self) -> bool:
        """Whether a track named Forced, SDH or Commentary also gets that flag written, in the selected batch."""
        key = self._workspace.key
        return key is not None and self._workspace.batches.profile(key).for_stage("metadata").write_implied_flags

    @property
    def flags_from_names(self) -> bool:
        """Whether the rules of the selected batch read a track named Forced, SDH or Commentary as having that flag."""
        key = self._workspace.key
        return key is not None and self._workspace.batches.profile(key).for_stage("tracks").flags_from_names

    def set_flags_from_names(self, on: bool) -> None:
        workspace = self._workspace
        if workspace.key is None or workspace.locked or on == self.flags_from_names:
            return
        workspace.set_tracks(replace(workspace.own_tracks(), flags_from_names=on))

    @property
    def implied_nothing(self) -> bool:
        """With "Write flags the names imply" on, whether no track of the open place lacks a flag its name implies.
        False while the plan is not current, and without MKVToolNix, which plans no names."""
        status = (self._workspace.statuses or {}).get("mkvtoolnix")
        found = status is not None and status.state is State.FOUND
        return found and self.write_implied_flags and self._workspace.shown.get("implied") == 0

    def set_write_implied_flags(self, on: bool) -> None:
        workspace = self._workspace
        if workspace.key is None or workspace.locked or on == self.write_implied_flags:
            return
        metadata = workspace.batches.profile(workspace.key).for_stage("metadata")
        workspace.set_options("metadata", replace(metadata, write_implied_flags=on))
