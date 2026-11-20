"""Profile files in a folder, plus the read-only built-in starter profiles.

A profile's name is its file name without `.json`, so renaming a file by hand renames the profile.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

from showrunner.app.profiles.errors import (
    InvalidProfileNameError,
    ProfileExistsError,
    ProfileNotFoundError,
    ReadOnlyProfileError,
    UnreadableProfileError,
)
from showrunner.app.profiles.profile import Profile, profile_from_json, profile_to_json
from showrunner.app.storage.files import write_json_atomic
from showrunner.app.storage.paths import profiles_dir
from showrunner.core.options.registry import REGISTRY, OptionsRegistry
from showrunner.core.options.serialization import Loaded

DEFAULT_PROFILE_NAME = "Default"
BUILTIN_NAMES = (DEFAULT_PROFILE_NAME,)

_SUFFIX = ".json"
_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_DEVICE_NAMES = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)
_MAX_NAME_LENGTH = 100


def validate_name(name: str) -> None:
    """Raise InvalidProfileNameError unless `name` is usable as a file name on every supported OS."""
    if (
        not name
        or len(name) > _MAX_NAME_LENGTH
        or name != name.strip()
        or name.endswith(".")
        or _FORBIDDEN_CHARS.search(name)
        or _WINDOWS_DEVICE_NAMES.fullmatch(name)
    ):
        raise InvalidProfileNameError(name)


class ProfileStore:
    def __init__(self, root: Path | None = None, registry: OptionsRegistry = REGISTRY) -> None:
        self._root = root if root is not None else profiles_dir()
        self._registry = registry

    def is_builtin(self, name: str) -> bool:
        return name.casefold() in {builtin.casefold() for builtin in BUILTIN_NAMES}

    def names(self) -> list[str]:
        """Built-in names first, then saved profiles in alphabetical order."""
        saved = sorted(
            (p.stem for p in self._root.glob(f"*{_SUFFIX}") if p.is_file() and not self.is_builtin(p.stem)),
            key=str.casefold,
        )
        return [*BUILTIN_NAMES, *saved]

    def load(self, name: str) -> Loaded[Profile]:
        if self.is_builtin(name):
            builtin = next(b for b in BUILTIN_NAMES if b.casefold() == name.casefold())
            return Loaded(Profile.defaults(builtin, self._registry))
        path = self._path(name)
        if not path.is_file():
            raise ProfileNotFoundError(name)
        return self._read(path, name)

    def save(self, profile: Profile) -> None:
        """Write or overwrite a saved profile. Built-ins are refused: use `save_as` for a copy."""
        self._require_editable(profile.name)
        write_json_atomic(self._path(profile.name), profile_to_json(profile, self._registry))

    def save_as(self, profile: Profile, name: str) -> Profile:
        """Save `profile` under a new name. Never overwrites."""
        self._require_free(name)
        copy = replace(profile, name=name)
        write_json_atomic(self._path(name), profile_to_json(copy, self._registry))
        return copy

    def duplicate(self, name: str, new_name: str) -> Profile:
        return self.save_as(self.load(name).value, new_name)

    def rename(self, name: str, new_name: str) -> None:
        self._require_editable(name)
        path = self._path(name)
        if not path.is_file():
            raise ProfileNotFoundError(name)
        # A change of letter case only is the same name on case-insensitive file systems.
        if name.casefold() != new_name.casefold():
            self._require_free(new_name)
        else:
            validate_name(new_name)
        path.rename(self._path(new_name))

    def delete(self, name: str) -> None:
        self._require_editable(name)
        path = self._path(name)
        if not path.is_file():
            raise ProfileNotFoundError(name)
        path.unlink()

    def import_file(self, source: Path, name: str | None = None) -> Loaded[Profile]:
        """Copy a profile file into the store. The name defaults to the file name without extension."""
        name = source.stem if name is None else name
        self._require_free(name)
        loaded = self._read(source, name)
        write_json_atomic(self._path(name), profile_to_json(loaded.value, self._registry))
        return loaded

    def export(self, name: str, destination: Path) -> None:
        write_json_atomic(destination, profile_to_json(self.load(name).value, self._registry))

    def _path(self, name: str) -> Path:
        validate_name(name)
        return self._root / f"{name}{_SUFFIX}"

    def _require_editable(self, name: str) -> None:
        if self.is_builtin(name):
            raise ReadOnlyProfileError(name)

    def _require_free(self, name: str) -> None:
        validate_name(name)
        if name.casefold() in {existing.casefold() for existing in self.names()}:
            raise ProfileExistsError(name)

    def _read(self, path: Path, name: str) -> Loaded[Profile]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (
            OSError,
            ValueError,
        ) as error:  # ValueError covers JSON and Unicode decoding errors
            raise UnreadableProfileError(str(path)) from error
        return profile_from_json(name, data, self._registry)
