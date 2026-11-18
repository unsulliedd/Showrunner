"""Batches: the places a workspace shows (a whole show, a season, an episode, the extras of a show or one of them, the
Movies group or one movie) and the choices made on each.

A choice made on a place reaches everything inside it: a show's reaches its seasons and their episodes and its extras,
a season's its episodes, and the Movies group's every movie. A place's own choice overrides the one it receives, for
that place only. The show and the Movies group follow a profile: they hold a working copy of it, which Save writes back
and Revert returns to. A season, an episode, an extra and a movie hold only what they set themselves (`places.Layer`),
laid over what they receive, so a later change on the show still reaches them wherever they did not choose otherwise;
removing a place's own choices (`forget`) makes it follow its parent again, and `discard` does so for a place and
everything inside it. Preview plans each file with its own combined options.

Whether a place is excluded from every run is a value per place too, kept apart from the choices (`Exclusions`): a
show's excludes its seasons, episodes and extras unless one of them holds its own value, and Discard leaves it alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from showrunner.app.batches.choices import NO_CHOICE, TrackChoice, TrackSignature, choice_of, choose
from showrunner.app.batches.exclusions import Exclusions
from showrunner.app.batches.places import (
    Layer,
    choice_count,
    combine,
    difference,
    layer_from_json,
    layer_to_json,
    own_rules,
)
from showrunner.app.batches.places import with_options as layer_with_options
from showrunner.app.profiles.errors import ProfileError
from showrunner.app.profiles.profile import Profile, profile_from_json, profile_to_json
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.app.profiles.working import WorkingCopy
from showrunner.core.media import Episode, Extra, MediaItem
from showrunner.stages.tracks import TracksOptions


class BatchKind(StrEnum):
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"
    EXTRAS = "extras"  # the extras of a show, listed after its seasons
    EXTRA = "extra"
    MOVIE = "movie"
    MOVIES = "movies"  # the Movies group: every movie in the library


class Media(StrEnum):
    """What a batch holds; a new show or the Movies group starts from the profile last used for the same media."""

    EPISODES = "episodes"
    MOVIES = "movies"


@dataclass(frozen=True, slots=True)
class BatchKey:
    """Names a place by what it is rather than where its files are, so a renamed or moved file keeps its choices."""

    kind: BatchKind
    media: Media
    title: str = ""  # the show's or the movie's
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    name: str = ""  # an extra's title, which tells it from the other extras of its show

    @classmethod
    def of(cls, item: MediaItem, *, whole_show: bool = False) -> BatchKey:
        """The season of an episode, the extras group of an extra (the show with `whole_show`), or the movie itself."""
        identity = item.identity
        if isinstance(identity, Extra):
            if whole_show:
                return cls(BatchKind.SHOW, Media.EPISODES, identity.show, identity.year)
            return cls(BatchKind.EXTRAS, Media.EPISODES, identity.show, identity.year)
        if isinstance(identity, Episode):
            if whole_show:
                return cls(BatchKind.SHOW, Media.EPISODES, identity.show, identity.year)
            return cls(BatchKind.SEASON, Media.EPISODES, identity.show, identity.year, identity.season)
        return cls(BatchKind.MOVIE, Media.MOVIES, identity.title, identity.year)

    @classmethod
    def file(cls, item: MediaItem) -> BatchKey:
        """The place of one file: its episode, its extra, or its movie."""
        identity = item.identity
        if isinstance(identity, Extra):
            return cls(BatchKind.EXTRA, Media.EPISODES, identity.show, identity.year, name=identity.title)
        if isinstance(identity, Episode):
            season, episode = identity.season, identity.episode
            return cls(BatchKind.EPISODE, Media.EPISODES, identity.show, identity.year, season, episode)
        return cls.of(item)

    @classmethod
    def movies(cls) -> BatchKey:
        return cls(BatchKind.MOVIES, Media.MOVIES)

    @property
    def parent(self) -> BatchKey | None:
        """The place this one receives choices from; None for a show and for the Movies group."""
        if self.kind is BatchKind.EPISODE:
            return BatchKey(BatchKind.SEASON, self.media, self.title, self.year, self.season)
        if self.kind is BatchKind.EXTRA:
            return BatchKey(BatchKind.EXTRAS, self.media, self.title, self.year)
        if self.kind in (BatchKind.SEASON, BatchKind.EXTRAS):
            return BatchKey(BatchKind.SHOW, self.media, self.title, self.year)
        if self.kind is BatchKind.MOVIE:
            return BatchKey.movies()
        return None

    def in_show(self, show: BatchKey) -> BatchKey:
        """This place named as a place of `show`. The library lists a show's files under one row whatever the case of
        its title or the year each file names, so every place in that row takes the row's show as its root."""
        return replace(self, title=show.title, year=show.year) if self.media is Media.EPISODES else self

    def within(self, place: BatchKey) -> bool:
        """Whether this place is `place` or lies inside it."""
        key: BatchKey | None = self
        while key is not None:
            if key == place:
                return True
            key = key.parent
        return False

    @property
    def root(self) -> BatchKey:
        """The show or the Movies group the place lies in; it follows the profile."""
        key = self
        while key.parent is not None:
            key = key.parent
        return key


@dataclass(frozen=True, slots=True)
class Discard:
    """What discarding the changes of a place removes."""

    own: int  # the own choices of a season, an episode, an extra or a movie
    edited: bool  # a show's or the Movies group's unsaved edits of its profile
    inside: int  # the own choices of the places inside it
    places: int  # how many places inside it hold some

    @property
    def anything(self) -> bool:
        return bool(self.own or self.edited or self.inside)


class Batches:
    """The working copy of every show and of the Movies group, created from a profile the first time it is asked for,
    and the own choices of every nearer place."""

    def __init__(self, store: ProfileStore, last_used: dict[Media, str] | None = None) -> None:
        self._store = store
        self._copies: dict[BatchKey, WorkingCopy] = {}  # by root
        self._layers: dict[BatchKey, Layer] = {}  # a season's, an episode's, an extra's or a movie's own choices
        self.exclusions = Exclusions()
        self.last_used: dict[Media, str] = dict(last_used or {})  # media -> the profile a new root starts from

    def copy(self, key: BatchKey) -> WorkingCopy:
        """The working copy of the profile the place follows: its show's, or the Movies group's for a movie. The
        profile pill, Save and Revert work on it, from whichever place inside it is open."""
        root = key.root
        if root not in self._copies:
            self._copies[root] = self._open(self.last_used.get(root.media, DEFAULT_PROFILE_NAME))
        return self._copies[root]

    def profile(self, key: BatchKey) -> Profile:
        """What Preview plans the place's files with: the root's working copy, unsaved edits included, with the own
        choices of each place down to `key` laid over it."""
        return self._combined(key, {})

    def received(self, key: BatchKey) -> Profile | None:
        """What the place receives from above; None for a show and for the Movies group."""
        return self.profile(key.parent) if key.parent is not None else None

    def file_profiles(self, items: Sequence[MediaItem], under: BatchKey) -> dict[Path, Profile]:
        """Each file's options, the files lying in place `under` (see `BatchKey.in_show`). Files whose places set
        nothing of their own share their parent's object, so a planner can plan them as one group."""
        cache: dict[BatchKey, Profile] = {}
        return {item.file.path: self._combined(BatchKey.file(item).in_show(under), cache) for item in items}

    def own(self, key: BatchKey) -> Layer:
        """The fields a season, an episode, an extra or a movie set itself; empty for a root, whose choices are its
        copy."""
        return self._layers.get(key, {})

    def own_tracks(self, key: BatchKey) -> TracksOptions:
        """The place's track options with only its own rules, which rule edits work on; the other fields are as the
        place has them."""
        tracks = self.profile(key).for_stage("tracks")
        return tracks if key.parent is None else replace(tracks, rules=own_rules(self.own(key)))

    def received_choice(self, key: BatchKey, signature: TrackSignature) -> TrackChoice:
        """The choice on `signature` the place receives from above; none for a root."""
        received = self.received(key)
        return choice_of(received.for_stage("tracks"), signature) if received is not None else NO_CHOICE

    def with_choice(self, key: BatchKey, signature: TrackSignature, choice: TrackChoice) -> TracksOptions:
        """The place's own track options (`own_tracks`) with `choice` as its choice on `signature`. A choice equal to
        the one received leaves the place following its parent there; another one, no choice included, overrides it
        for this place."""
        return choose(self.own_tracks(key), signature, choice, self.received_choice(key, signature))

    def set_options(self, key: BatchKey, stage_id: str, options: Any) -> None:
        """Set a place's options of one stage. A root's go into its working copy. A nearer place keeps the fields that
        differ from what it receives, and the rules of `options` as its own rules (see `own_tracks`)."""
        if key.parent is None:
            self.copy(key).set_options(stage_id, options)
            return
        received = self.profile(key.parent).for_stage(stage_id)
        layer = layer_with_options(self.own(key), stage_id, options, received)
        if layer:
            self._layers[key] = layer
        else:
            self._layers.pop(key, None)

    def origins(self, key: BatchKey) -> list[BatchKey]:
        """For each rule of the place's tracks options, in order, the place that set it. The root's working copy
        counts as the root's, the profile's own rules included."""
        if key.parent is None:
            return [key] * len(self.copy(key).profile.for_stage("tracks").rules)
        own = own_rules(self.own(key))
        received = self.profile(key.parent).for_stage("tracks").rules
        from_above = self.origins(key.parent)
        if not own:
            return from_above
        kept = self.profile(key).for_stage("tracks").rules[len(own) :]
        result, n = [key] * len(own), 0
        # The rules kept from above are the same objects, in the same order.
        for rule, origin in zip(received, from_above, strict=True):
            if n < len(kept) and kept[n] is rule:
                result.append(origin)
                n += 1
        return result

    def switch(self, key: BatchKey, name: str) -> None:
        """Start the place's root from another profile; its unsaved edits are dropped, so the caller asks first."""
        self.copy(key).switch(name)
        self.last_used[key.media] = name

    def save_as(self, key: BatchKey, name: str) -> None:
        """Raises `ProfileExistsError` or `InvalidProfileNameError` and then changes nothing."""
        self.copy(key).save_as(name)
        self.last_used[key.media] = name

    def following(self, name: str) -> list[BatchKey]:
        """The roots whose working copy starts from profile `name`."""
        return [key for key, copy in self._copies.items() if copy.name.casefold() == name.casefold()]

    def rename_profile(self, name: str, new_name: str) -> None:
        """Rename a saved profile's file; the roots that follow it keep their edits under the new name."""
        self._store.rename(name, new_name)
        for key in self.following(name):
            self._copies[key].renamed(new_name)
        self.last_used = {media: new_name if used == name else used for media, used in self.last_used.items()}

    def delete_profile(self, name: str) -> None:
        """Delete a saved profile's file. A root that followed it keeps what it planned with, as edits over the
        default profile, so nothing chosen is lost; a new root of that kind starts from the default."""
        self._store.delete(name)
        for key in self.following(name):
            edited = self._copies[key].profile
            copy = self._copies[key] = self._open(DEFAULT_PROFILE_NAME)
            for stage_id, options in edited.options.items():
                copy.set_options(stage_id, options)
        self.last_used = {media: used for media, used in self.last_used.items() if used != name}

    def edit_profile(self, name: str, stage_id: str, **changes: Any) -> None:
        """Change fields of one stage in a saved profile's file. A root that follows it takes each change unless
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
        """Drop the place's own choices, nothing inside it: a root goes back to its profile as saved (the profile it
        follows now, not the one a new root would start from), a nearer place follows its parent."""
        if key.parent is None:
            if key in self._copies:
                self._copies[key].revert()
        else:
            self._layers.pop(key, None)

    def discard_of(self, key: BatchKey) -> Discard:
        """What `discard` would remove from the place and from every place inside it."""
        copy = self._copies.get(key) if key.parent is None else None
        inside = [layer for place, layer in self._layers.items() if place != key and place.within(key)]
        return Discard(
            own=choice_count(self.own(key)),
            edited=copy is not None and copy.changed,
            inside=sum(choice_count(layer) for layer in inside),
            places=len(inside),
        )

    def discard(self, key: BatchKey) -> None:
        """Discard the changes of the place and of every place inside it, so each follows its parent again."""
        for place in [place for place in self._layers if place.within(key)]:
            self.forget(place)
        if key.parent is None:
            self.forget(key)

    def is_excluded(self, key: BatchKey) -> bool:
        return self.exclusions.excluded(key)

    def set_excluded(self, key: BatchKey, excluded: bool) -> None:
        """Exclude the place and everything inside it, or include it again; an own value inside wins for that place."""
        self.exclusions.set(key, excluded)

    def excluded_files(self, items: Sequence[MediaItem], under: BatchKey) -> set[Path]:
        """The files among `items`, lying in place `under` (see `BatchKey.in_show`), that are excluded."""
        return {i.file.path for i in items if self.exclusions.excluded(BatchKey.file(i).in_show(under))}

    def to_json(self) -> dict[str, Any]:
        """The state to keep with the workspace, so unsaved edits and exclusions survive a restart."""
        return {
            "last_used": {media.value: name for media, name in self.last_used.items()},
            "batches": [
                {"key": _key_json(key), "profile": copy.name, "options": profile_to_json(copy.profile)}
                for key, copy in self._copies.items()
            ],
            "places": [{"key": _key_json(key), "own": layer_to_json(layer)} for key, layer in self._layers.items()],
            "excluded": [{"key": _key_json(key), "value": value} for key, value in self.exclusions.values.items()],
        }

    @classmethod
    def from_json(cls, store: ProfileStore, data: Any) -> Batches:
        """Forgiving like a profile file: an entry that cannot be read is skipped, and a root whose profile is gone
        keeps its edits over the default profile.

        A season or a movie stored before places passed choices down was a whole edited profile of its own. What was
        changed in it becomes that place's own choices (`places.difference`), so it plans as before wherever it chose
        and follows its show elsewhere. Its show is started from its profile when the show was never opened. Of the
        old selections, named by their files, the last becomes the Movies group."""
        data = data if isinstance(data, dict) else {}
        last = data.get("last_used")
        last_used = {
            Media(media): name
            for media, name in (last.items() if isinstance(last, dict) else ())
            if media in set(Media) and isinstance(name, str)
        }
        batches = cls(store, last_used)
        entries = data.get("batches")
        whole: list[tuple[BatchKey, str, Profile]] = []
        for entry in entries if isinstance(entries, list) else ():
            try:
                key = _key_from_json(entry["key"])
                name = entry["profile"]
                if not isinstance(name, str):
                    raise TypeError("a profile name is text")
                edited = profile_from_json(name, entry["options"]).value
            except (AttributeError, KeyError, TypeError, ValueError, ProfileError):
                continue
            whole.append((key, name, edited))
        # The roots first, so an old season is compared with its show's copy.
        for key, name, edited in sorted(whole, key=lambda found: found[0].parent is not None):
            if key.parent is None:
                copy = batches._copies[key] = batches._open(name)
                for stage_id, options in edited.options.items():
                    copy.set_options(stage_id, options)
                continue
            if key.root not in batches._copies:
                batches._copies[key.root] = batches._open(name)
            root, received = batches._copies[key.root], batches.profile(key.parent)
            # On the root's profile, only what the place changed there is its own; on another profile, what it planned
            # with that the root does not give.
            base = root.saved if root.name.casefold() == name.casefold() else received
            if layer := difference(edited, base, received):
                batches._layers[key] = layer
        places = data.get("places")
        for entry in places if isinstance(places, list) else ():
            try:
                key = _key_from_json(entry["key"])
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
            if key.parent is not None and (layer := layer_from_json(entry.get("own"))):
                batches._layers[key] = layer
        excluded = data.get("excluded")
        for entry in excluded if isinstance(excluded, list) else ():
            try:
                key, value = _key_from_json(entry["key"]), entry["value"]
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
            if type(value) is bool:
                batches.exclusions.values[key] = value
        return batches

    def _combined(self, key: BatchKey, cache: dict[BatchKey, Profile]) -> Profile:
        if key not in cache:
            parent = key.parent
            if parent is None:
                cache[key] = self.copy(key).profile
            else:
                received = self._combined(parent, cache)
                layer = self._layers.get(key)
                cache[key] = combine(received, layer) if layer else received
        return cache[key]

    def _open(self, name: str) -> WorkingCopy:
        try:
            return WorkingCopy(self._store, name)
        except ProfileError:
            return WorkingCopy(self._store, DEFAULT_PROFILE_NAME)


def _key_json(key: BatchKey) -> dict[str, Any]:
    return asdict(key)


def _key_from_json(data: Any) -> BatchKey:
    """A selection stored by its files before is read as the Movies group."""
    if not isinstance(data, dict):
        raise TypeError("a batch key is an object")
    if data.get("kind") in ("selection", BatchKind.MOVIES):
        return BatchKey.movies()
    kind, media = BatchKind(data["kind"]), Media(data["media"])
    year, season, episode = data.get("year"), data.get("season"), data.get("episode")
    if not all(value is None or type(value) is int for value in (year, season, episode)):
        raise TypeError("a batch key has a wrong value")
    title, name = data.get("title", ""), data.get("name", "")
    if not isinstance(title, str) or not isinstance(name, str):
        raise TypeError("a batch key has a wrong value")
    return BatchKey(kind, media, title, year, season, episode, name)
