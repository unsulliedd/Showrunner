"""The working copy of the active profile: edits land here first, Preview uses them, and Save writes them."""

from __future__ import annotations

from typing import Any

from showrunner.app.profiles.profile import Profile
from showrunner.app.profiles.store import ProfileStore


class WorkingCopy:
    """The active profile as saved and as edited. Options are frozen dataclasses, but their lists and dicts are
    not: an edit always builds new ones (`dataclasses.replace` with a new list), so the saved copy never changes
    behind the working one."""

    def __init__(self, store: ProfileStore, name: str) -> None:
        self._store = store
        self._saved = store.load(name).value
        self._current = self._saved

    @property
    def store(self) -> ProfileStore:
        return self._store

    @property
    def profile(self) -> Profile:
        """The profile as edited; what Preview plans with."""
        return self._current

    @property
    def saved(self) -> Profile:
        return self._saved

    @property
    def name(self) -> str:
        return self._current.name

    @property
    def changed(self) -> bool:
        return self._current != self._saved

    @property
    def read_only(self) -> bool:
        return self._store.is_builtin(self.name)

    def set_options(self, stage_id: str, options: Any) -> None:
        self._current = self._current.with_options(stage_id, options)

    def save(self) -> None:
        """Raises `ReadOnlyProfileError` for a built-in profile."""
        self._store.save(self._current)
        self._saved = self._current

    def save_as(self, name: str) -> None:
        """Write the edits as a new profile, which becomes the active one. Raises `ProfileExistsError` or
        `InvalidProfileNameError` and then changes nothing."""
        self._saved = self._current = self._store.save_as(self._current, name)

    def revert(self) -> None:
        self._current = self._saved

    def switch(self, name: str) -> None:
        """Make another profile active; unsaved edits are dropped, so the caller asks first."""
        self._saved = self._current = self._store.load(name).value

    def renamed(self, name: str) -> None:
        """The active profile's file was renamed; the edits stay."""
        self._saved = self._store.load(name).value
        self._current = Profile(name, self._current.options)
