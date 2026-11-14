"""The working copy of the active profile as the window sees it: every change of it becomes one signal."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.app.jobs.blocked import StageBlock, blocked_stages
from showrunner.app.profiles.errors import ProfileError
from showrunner.app.profiles.profile import Profile
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.app.profiles.working import WorkingCopy
from showrunner.app.settings.app_settings import load_settings, save_settings

_log = logging.getLogger(__name__)


class ProfileSession(QObject):
    """Owns the `WorkingCopy`. `changed` fires after an edit, a save, a revert or a switch; `profiles_changed`
    after a profile file was added, renamed or removed, for the lists that name them."""

    changed = Signal()
    profiles_changed = Signal()

    def __init__(self, store: ProfileStore | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        store = store or ProfileStore()
        name = load_settings().value.active_profile
        try:
            self._copy = WorkingCopy(store, name)
        except ProfileError:
            _log.warning("Profile %r could not be loaded; using %s", name, DEFAULT_PROFILE_NAME)
            self._copy = WorkingCopy(store, DEFAULT_PROFILE_NAME)
        self._blocks: dict[str, StageBlock] | None = None

    @property
    def store(self) -> ProfileStore:
        return self._copy.store

    @property
    def profile(self) -> Profile:
        return self._copy.profile

    @property
    def saved(self) -> Profile:
        return self._copy.saved

    @property
    def name(self) -> str:
        return self._copy.name

    @property
    def is_changed(self) -> bool:
        return self._copy.changed

    @property
    def read_only(self) -> bool:
        return self._copy.read_only

    def options(self, stage_id: str) -> Any:
        return self._copy.profile.for_stage(stage_id)

    def blocks(self) -> dict[str, StageBlock]:
        """The stages the working copy's problems block; worked out once per change."""
        if self._blocks is None:
            self._blocks = blocked_stages(self._copy.profile)
        return self._blocks

    def set_options(self, stage_id: str, options: Any) -> None:
        if options == self.options(stage_id):
            return
        self._copy.set_options(stage_id, options)
        self._emit()

    def update(self, stage_id: str, **changes: Any) -> None:
        """Change some fields of one stage's options."""
        self.set_options(stage_id, replace(self.options(stage_id), **changes))

    def save(self) -> None:
        self._copy.save()
        self._emit()

    def save_as(self, name: str) -> None:
        self._copy.save_as(name)
        self._remember()
        self.profiles_changed.emit()
        self._emit()

    def revert(self) -> None:
        self._copy.revert()
        self._emit()

    def switch(self, name: str) -> None:
        """Unsaved edits are dropped; the caller asks first."""
        self._copy.switch(name)
        self._remember()
        self._emit()

    def renamed(self, old: str, new: str) -> None:
        if old == self.name:
            self._copy.renamed(new)
            self._remember()
            self._emit()
        self.profiles_changed.emit()

    def _emit(self) -> None:
        self._blocks = None
        self.changed.emit()

    def _remember(self) -> None:
        try:
            save_settings(replace(load_settings().value, active_profile=self.name))
        except OSError:
            _log.exception("Could not save the active profile")
