"""Batches: what one workspace shows (a season, a whole show, a movie or a hand-made selection), each with its own
working copy of a profile.

A choice belongs to the batch it was made in. Chips, cards, rules and templates edit that batch's working copy only,
so dropping a commentary track for one movie never changes another show; Save writes the copy back to its profile,
Revert returns to the profile. Preview plans a batch's files with that batch's profile, one profile per preview.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from showrunner.app.profiles.errors import ProfileError
from showrunner.app.profiles.profile import Profile, profile_from_json, profile_to_json
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.app.profiles.working import WorkingCopy
from showrunner.core.media import Episode, MediaItem


class BatchKind(StrEnum):
    SEASON = "season"
    SHOW = "show"
    MOVIE = "movie"
    SELECTION = "selection"


class Media(StrEnum):
    """What a batch holds; a new batch starts from the profile last used for the same media."""

    EPISODES = "episodes"
    MOVIES = "movies"


@dataclass(frozen=True, slots=True)
class BatchKey:
    """Names a batch by what it is rather than where its files are, so a renamed or moved file stays in its batch.
    A selection is the one batch named by its files."""

    kind: BatchKind
    media: Media
    title: str = ""  # the show's or the movie's
    year: int | None = None
    season: int | None = None
    paths: tuple[str, ...] = ()  # a selection's files

    @classmethod
    def of(cls, item: MediaItem, *, whole_show: bool = False) -> BatchKey:
        """The season of an episode (the show with `whole_show`), or the movie itself."""
        identity = item.identity
        if isinstance(identity, Episode):
            if whole_show:
                return cls(BatchKind.SHOW, Media.EPISODES, identity.show, identity.year)
            return cls(BatchKind.SEASON, Media.EPISODES, identity.show, identity.year, identity.season)
        return cls(BatchKind.MOVIE, Media.MOVIES, identity.title, identity.year)

    @classmethod
    def selection(cls, paths: list[Path], media: Media) -> BatchKey:
        return cls(BatchKind.SELECTION, media, paths=tuple(sorted(str(path) for path in paths)))


class Batches:
    """The working copy of every batch opened, created from a profile the first time a batch is asked for."""

    def __init__(self, store: ProfileStore, last_used: dict[Media, str] | None = None) -> None:
        self._store = store
        self._copies: dict[BatchKey, WorkingCopy] = {}
        self.last_used: dict[Media, str] = dict(last_used or {})  # media -> the profile a new batch starts from

    def copy(self, key: BatchKey) -> WorkingCopy:
        """The batch's working copy; edits go through it (`set_options`, `save`, `revert`)."""
        if key not in self._copies:
            self._copies[key] = self._open(self.last_used.get(key.media, DEFAULT_PROFILE_NAME))
        return self._copies[key]

    def profile(self, key: BatchKey) -> Profile:
        """What Preview plans the batch's files with, unsaved edits included.

        Every file of a batch gets the same profile. An exception for one episode would be kept with the batch as
        well, as options laid over this profile for that file alone.
        """
        return self.copy(key).profile

    def switch(self, key: BatchKey, name: str) -> None:
        """Start the batch from another profile; its unsaved edits are dropped, so the caller asks first."""
        self.copy(key).switch(name)
        self.last_used[key.media] = name

    def save_as(self, key: BatchKey, name: str) -> None:
        """Raises `ProfileExistsError` or `InvalidProfileNameError` and then changes nothing."""
        self.copy(key).save_as(name)
        self.last_used[key.media] = name

    def following(self, name: str) -> list[BatchKey]:
        """The batches whose working copy starts from profile `name`."""
        return [key for key, copy in self._copies.items() if copy.name.casefold() == name.casefold()]

    def rename_profile(self, name: str, new_name: str) -> None:
        """Rename a saved profile's file; the batches that follow it keep their edits under the new name."""
        self._store.rename(name, new_name)
        for key in self.following(name):
            self._copies[key].renamed(new_name)
        self.last_used = {media: new_name if used == name else used for media, used in self.last_used.items()}

    def delete_profile(self, name: str) -> None:
        """Delete a saved profile's file. A batch that followed it keeps what it planned with, as edits over the
        default profile, so nothing chosen is lost; a new batch of that kind starts from the default."""
        self._store.delete(name)
        for key in self.following(name):
            edited = self._copies[key].profile
            copy = self._copies[key] = self._open(DEFAULT_PROFILE_NAME)
            for stage_id, options in edited.options.items():
                copy.set_options(stage_id, options)
        self.last_used = {media: used for media, used in self.last_used.items() if used != name}

    def edit_profile(self, name: str, stage_id: str, **changes: Any) -> None:
        """Change fields of one stage in a saved profile's file. A batch that follows it takes each change unless
        its working copy already changed that field, so an unsaved choice is kept and nothing reads as edited
        that was not."""
        saved = self._store.load(name).value
        old = saved.for_stage(stage_id)
        self._store.save(saved.with_options(stage_id, replace(old, **changes)))
        for key in self.following(name):
            copy = self._copies[key]
            current = copy.profile.for_stage(stage_id)
            follow = {
                field: value for field, value in changes.items() if getattr(current, field) == getattr(old, field)
            }
            copy.reload()
            copy.set_options(stage_id, replace(current, **follow))

    def forget(self, key: BatchKey) -> None:
        """Drop the batch's working copy; the next `copy` starts from a profile again."""
        self._copies.pop(key, None)

    def to_json(self) -> dict[str, Any]:
        """The state to keep with the workspace, so unsaved edits survive a restart."""
        return {
            "last_used": {media.value: name for media, name in self.last_used.items()},
            "batches": [
                {"key": _key_json(key), "profile": copy.name, "options": profile_to_json(copy.profile)}
                for key, copy in self._copies.items()
            ],
        }

    @classmethod
    def from_json(cls, store: ProfileStore, data: Any) -> Batches:
        """Forgiving like a profile file: an entry that cannot be read is skipped, and a batch whose profile is
        gone keeps its edits over the default profile."""
        data = data if isinstance(data, dict) else {}
        last = data.get("last_used")
        last_used = {
            Media(media): name
            for media, name in (last.items() if isinstance(last, dict) else ())
            if media in set(Media) and isinstance(name, str)
        }
        batches = cls(store, last_used)
        entries = data.get("batches")
        for entry in entries if isinstance(entries, list) else ():
            try:
                key = _key_from_json(entry["key"])
                copy = batches._open(entry["profile"])
                edited = profile_from_json(copy.name, entry["options"]).value
            except (AttributeError, KeyError, TypeError, ValueError, ProfileError):
                continue
            for stage_id, options in edited.options.items():
                copy.set_options(stage_id, options)
            batches._copies[key] = copy
        return batches

    def _open(self, name: str) -> WorkingCopy:
        try:
            return WorkingCopy(self._store, name)
        except ProfileError:
            return WorkingCopy(self._store, DEFAULT_PROFILE_NAME)


def _key_json(key: BatchKey) -> dict[str, Any]:
    return {**asdict(key), "paths": list(key.paths)}


def _key_from_json(data: Any) -> BatchKey:
    if not isinstance(data, dict):
        raise TypeError("a batch key is an object")
    year, season, paths = data.get("year"), data.get("season"), data.get("paths", [])
    if not all(value is None or type(value) is int for value in (year, season)) or not isinstance(paths, list):
        raise TypeError("a batch key has a wrong value")
    title = data.get("title", "")
    if not isinstance(title, str) or not all(isinstance(path, str) for path in paths):
        raise TypeError("a batch key has a wrong value")
    return BatchKey(BatchKind(data["kind"]), Media(data["media"]), title, year, season, tuple(paths))
