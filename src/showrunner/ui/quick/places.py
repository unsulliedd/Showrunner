"""What the user does to the open place as a whole: its profile pill, the library row's menu, Keep these files as they
are, Exclude and Include, and Discard changes, with where each marked field's value comes from."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.app.batches.batch import BatchKey, BatchKind, Media
from showrunner.app.jobs.groups import TITLE_TEMPLATE, TRACK_TEMPLATES
from showrunner.app.profiles.errors import ProfileError, ProfileExistsError
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.facts import heading
from showrunner.ui.quick.folders import Folders
from showrunner.ui.quick.run import Run
from showrunner.ui.quick.workspace import Workspace

_log = logging.getLogger(__name__)

# The fields a view marks with where their value comes from, each beside its control. The track rules and the paired
# files are marked on their chips instead, the wanted languages and rule sets item by item.
_MARKED_FIELDS: tuple[tuple[str, str], ...] = (
    *(("naming", name) for name in (TITLE_TEMPLATE, *TRACK_TEMPLATES)),
    *(("naming", name.removesuffix("_template") + "_space") for name in (TITLE_TEMPLATE, *TRACK_TEMPLATES)),
    ("naming", "episode_code_format"),
    ("naming", "custom_tokens"),
    ("naming", "value_maps"),
    ("metadata", "untagged_language"),
    ("metadata", "write_implied_flags"),
    ("mux", "original"),
    ("tracks", "order"),
    ("tracks", "flags_from_names"),
    *(("subtitles", name) for name in ("translate", "reference", "sync", "lines", "model", "approval", "output")),
)


class Places(QObject):
    discard_asked = Signal()  # Discard changes was chosen: the window asks its question
    revert_asked = Signal()  # the profile pill's Revert was chosen: the window asks its question

    def __init__(self, workspace: Workspace, run: Run, folders: Folders, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._run = run
        self._folders = folders

    # Profile of the selected batch

    @property
    def profile(self) -> str:
        workspace = self._workspace
        if workspace.key is None:
            return workspace.batches.last_used.get(Media.EPISODES, DEFAULT_PROFILE_NAME)
        return workspace.batches.copy(workspace.key).name

    @property
    def profile_edited(self) -> bool:
        key = self._workspace.key
        return key is not None and self._workspace.batches.copy(key).changed

    @property
    def profiles(self) -> list[str]:
        return self._workspace.store.names()

    @property
    def profile_read_only(self) -> bool:
        """The built-in profile cannot be saved over; its edits go to a new profile through Save as."""
        key = self._workspace.key
        return key is not None and self._workspace.batches.copy(key).read_only

    def switch_profile(self, name: str) -> None:
        """Start the selected batch from another profile. An edited batch is discarded first, from the menu."""
        workspace = self._workspace
        key = workspace.key
        if key is None or workspace.locked or workspace.batches.copy(key).changed or name == self.profile:
            return
        workspace.batches.switch(key, name)
        workspace.copy_changed()

    def ask_revert(self) -> None:
        """The profile pill's Revert asks first, as Discard changes does: it cannot be undone."""
        if self._workspace.key is not None and not self._workspace.locked and self.profile_edited:
            self.revert_asked.emit()

    @property
    def revert_question(self) -> dict[str, str]:
        """The question asked before Revert: the show or Movies group whose working copy goes back to the profile as
        saved, and that the choices of the places inside it stay."""
        key = self._workspace.key
        if key is None:
            return {"heading": "", "text": "", "yes": tr("profile.revert_yes")}
        place = heading(key.root, ()).title
        lines = (
            tr("discard.edited", place=place, profile=self.profile),
            tr("profile.revert_inside", place=place),
            tr("discard.final"),
        )
        return {
            "heading": tr("profile.revert_heading", place=place, profile=self.profile),
            "text": "\n\n".join(lines),
            "yes": tr("profile.revert_yes"),
        }

    def discard_profile(self) -> None:
        """Revert the open place's show or Movies group to its profile as saved, once the question was answered."""
        workspace = self._workspace
        if workspace.key is not None and not workspace.locked:
            workspace.batches.copy(workspace.key).revert()
            workspace.copy_changed()

    def save_profile(self) -> None:
        """Write the batch's choices to its profile, so the next batch that starts from it has them too."""
        workspace = self._workspace
        if workspace.key is None or self.profile_read_only:
            return
        try:
            workspace.batches.copy(workspace.key).save()
        except (OSError, ProfileError):
            _log.exception("Could not save the profile")
        workspace.copy_changed()

    def save_profile_as(self, name: str) -> str:
        """Write the choices to a new profile, which the batch then follows; returns why not, or "" when saved."""
        workspace = self._workspace
        if workspace.key is None:
            return ""
        try:
            workspace.batches.save_as(workspace.key, name.strip())
        except ProfileExistsError:
            return tr("profile.error.exists", name=name.strip())
        except ProfileError:
            return tr("profile.error.name")
        except OSError as error:
            _log.exception("Could not save the profile")
            return str(error)
        workspace.copy_changed()
        return ""

    # Menu of the selected place

    @property
    def place_actions(self) -> list[dict[str, Any]]:
        """What the right-click menu of a library row offers for the selected place."""
        key = self._workspace.key
        excluded = self.place_excluded
        actions: list[dict[str, Any]] = [
            {"key": "discard", "text": tr("workspace.discard"), "enabled": self.can_discard},
            {
                "key": "include" if excluded else "exclude",
                "text": tr("workspace.include" if excluded else "workspace.exclude"),
                "tip": tr("workspace.include_tip" if excluded else "workspace.exclude_tip"),
                "enabled": key is not None and not self._workspace.locked,
            },
        ]
        if key is not None and key.parent is not None:
            actions.insert(1, {"key": "keep", "text": tr("workspace.keep"), "enabled": self.can_keep})
        actions.append({"key": "queue", "text": tr("queue.add"), "enabled": self._run.can_queue})
        if key is not None:
            actions.append(
                {
                    "key": "remove",
                    "text": tr("workspace.remove"),
                    "tip": tr("workspace.remove_tip"),
                    "enabled": self._folders.can_change_library,
                }
            )
        if folders := self._folders.folders_of_place():
            names = tr("common.list_separator").join(f.name or str(f) for f in folders)
            actions.append(
                {
                    "key": "close",
                    "text": tr("library.close"),
                    "tip": tr("library.close_tip", folders=names),
                    "enabled": self._folders.can_change_library,
                }
            )
        return actions

    def place_action(self, key: str) -> None:
        if key == "discard":
            self.ask_discard()
        elif key == "keep":
            self.keep_place()
        elif key in ("exclude", "include"):
            self.exclude_place(key == "exclude")
        elif key == "queue":
            self._run.add_to_queue()
        elif key == "remove":
            self._folders.remove_place()
        elif key == "close":
            self._folders.close_place_folders()

    # Keep these files as they are

    @property
    def can_keep(self) -> bool:
        """Something from above asks for a change in the selected place, which is not a show or the Movies group."""
        workspace = self._workspace
        return workspace.key is not None and not workspace.locked and workspace.batches.receives(workspace.key)

    def keep_place(self) -> None:
        """Keep the selected place's files as they are: nothing from above reaches it, its own choices stay. Asks
        nothing, since Discard changes takes it back."""
        workspace = self._workspace
        if workspace.key is not None and self.can_keep:
            workspace.batches.keep(workspace.key)
            workspace.refresh_excluded()
            workspace.copy_changed()

    @property
    def kept_text(self) -> str:
        """The line that marks a place kept as it is, or one inside a kept place; empty otherwise."""
        place: BatchKey | None = self._workspace.key
        while place is not None and place.parent is not None and not self._workspace.batches.kept(place):
            place = place.parent
        if place is None or place.parent is None:
            return ""
        parent = tr(f"discard.parent.{place.parent.kind.value}")
        if place == self._workspace.key:
            return tr("workspace.kept", parent=parent)
        return tr("workspace.kept_above", place=tr(f"discard.parent.{place.kind.value}"), parent=parent)

    @property
    def field_marks(self) -> dict[str, dict[str, str]]:
        """Where each field a view marks comes from, by `stage.field`: `from` the place above that set it, `over` the
        place whose value the selected place's own one overrides; both empty for a value set here with nothing above
        it, and for a show and the Movies group."""
        key = self._workspace.key
        if key is None or key.parent is None:
            return {}
        return {f"{stage_id}.{name}": self._field_mark(stage_id, name) for stage_id, name in _MARKED_FIELDS}

    def _field_mark(self, stage_id: str, name: str) -> dict[str, str]:
        key = self._workspace.key
        assert key is not None
        assert key.parent is not None
        batches = self._workspace.batches
        origin = batches.field_origin(key, stage_id, name)
        if origin is not None and origin != key:
            return {"from": tr(f"place.from.{origin.kind.value}"), "over": ""}
        above = batches.field_origin(key.parent, stage_id, name) if origin == key else None
        return {"from": "", "over": tr(f"place.over.{above.kind.value}") if above is not None else ""}

    # Exclude and Include

    @property
    def place_excluded(self) -> bool:
        """The selected place is out of every run, on its own or through a place above it."""
        key = self._workspace.key
        return key is not None and self._workspace.batches.is_excluded(key)

    def exclude_place(self, excluded: bool) -> None:
        """Exclude the selected place and everything inside it, or include it again; a place inside that holds a value
        of its own keeps it. Unlike a choice, it is kept until the user changes it, and Discard leaves it alone."""
        if self._workspace.key is not None:
            self._set_excluded(self._workspace.key, excluded)

    def exclude_file(self, path: str, excluded: bool) -> None:
        """Exclude or include one file of the selected batch, which is that file's own place."""
        item = self._workspace.file_item(path)
        if self._workspace.key is not None and item is not None:
            self._set_excluded(BatchKey.file(item).in_show(self._workspace.key), excluded)

    def _set_excluded(self, key: BatchKey, excluded: bool) -> None:
        workspace = self._workspace
        if workspace.locked:
            return
        workspace.batches.set_excluded(key, excluded)
        workspace.refresh_excluded()
        workspace.refresh()
        workspace.save_soon()
        workspace.batch_changed.emit()

    # Discard changes

    @property
    def can_discard(self) -> bool:
        """The selected place holds something to discard (its own choices, a root's unsaved edits, or choices of
        places inside it), and its files are not being applied."""
        workspace = self._workspace
        key = workspace.key
        return key is not None and not workspace.locked and workspace.batches.discard_of(key).anything

    def ask_discard(self) -> None:
        key = self._workspace.key
        if not self.can_discard or key is None:
            return
        if self._workspace.batches.discard_of(key).only_kept:
            self.discard_changes()
        else:
            self.discard_asked.emit()

    @property
    def discard_question(self) -> dict[str, str]:
        """The question asked before Discard changes: the place, what goes, and that it cannot be undone."""
        key = self._workspace.key
        if key is None:
            return {"heading": "", "text": "", "yes": tr("workspace.discard_yes")}
        found = self._workspace.batches.discard_of(key)
        batch = self._workspace.batch
        place = batch["title"]
        lines = []
        if found.own:
            parent = key.parent.kind.value if key.parent is not None else ""
            lines.append(
                tr(
                    "discard.own",
                    place=place,
                    choices=tr_plural("discard.choices", found.own),
                    parent=tr(f"discard.parent.{parent}"),
                )
            )
        if found.kept and key.parent is not None:
            lines.append(tr("discard.kept", place=place, parent=tr(f"discard.parent.{key.parent.kind.value}")))
        if found.edited:
            lines.append(tr("discard.edited", place=place, profile=self.profile))
        if found.inside:
            lines.append(
                tr(
                    "discard.inside",
                    place=place,
                    choices=tr_plural("discard.choices", found.inside),
                    places=tr_plural("discard.places", found.places),
                )
            )
        lines.append(tr("discard.final"))
        return {
            "heading": tr("discard.heading", place=place)
            if key.kind in (BatchKind.SHOW, BatchKind.MOVIES, BatchKind.MOVIE)
            else tr("discard.heading_in", place=place, over=batch["over"]),
            "text": "\n\n".join(lines),
            "yes": tr("workspace.discard_yes"),
        }

    def discard_changes(self) -> None:
        """Discard the changes of the selected place and of every place inside it, then plan and save as after any
        other choice."""
        workspace = self._workspace
        if workspace.key is not None and self.can_discard:
            workspace.batches.discard(workspace.key)
            workspace.refresh_excluded()
            workspace.copy_changed()
