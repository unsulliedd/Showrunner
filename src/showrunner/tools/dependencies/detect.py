"""Finding each program, reading its version, and answering which features are available."""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner.tools.dependencies.specs import SPECS, DependencySpec, Feature
from showrunner.tools.process import ProcessError, run

VERSION_TIMEOUT_SECONDS = 15.0


class State(StrEnum):
    FOUND = "found"
    OUTDATED = "outdated"
    # Present, but it did not run or did not print a version.
    BROKEN = "broken"
    MISSING = "missing"


class Location(StrEnum):
    """Where a program was found, in the order the places are searched."""

    USER = "user"
    TOOLS = "tools"
    PATH = "path"
    INSTALL_DIR = "install_dir"


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    spec_id: str
    state: State
    # The first executable of the spec; the others sit in the same folder.
    path: Path | None = None
    location: Location | None = None
    version: str | None = None
    # What the program printed when it ran but gave no version, or why it could not run.
    detail: str = ""

    def executable(self, name: str) -> Path | None:
        """The full path of one of the spec's executables, by its bare name."""
        return None if self.path is None else self.path.parent / file_name(name)


def file_name(name: str) -> str:
    """The file name of a program on this system: `.exe` is added on Windows unless the name has an extension."""
    return name + ".exe" if os.name == "nt" and not Path(name).suffix else name


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def parse_version(spec: DependencySpec, output: str) -> str | None:
    if spec.version_pattern is None:
        return None
    match = re.search(spec.version_pattern, output)
    return match.group(1) if match else None


def _expand(folder: str) -> Path | None:
    expanded = os.path.expandvars(folder)
    return None if "%" in expanded or "$" in expanded else Path(expanded)


def _candidates(spec: DependencySpec, tools_dir: Path, user_path: Path | None) -> Iterator[tuple[Location, Path]]:
    """Folders that may hold the program, in search order."""
    if user_path is not None:
        # The user may pick the program itself or the folder it is in.
        yield Location.USER, user_path.parent if user_path.is_file() else user_path
    own = tools_dir / spec.id
    if own.is_dir():
        # Archives keep their own layout (`bin/` and the like), so the program may sit below the top folder.
        first = file_name(spec.executables[0])
        yield Location.TOOLS, own
        for found in sorted(own.rglob(first)):
            yield Location.TOOLS, found.parent
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry.strip():
            yield Location.PATH, Path(entry.strip().strip('"'))
    for folder in spec.install_dirs:
        expanded = _expand(folder)
        if expanded is not None:
            yield Location.INSTALL_DIR, expanded


def locate(spec: DependencySpec, tools_dir: Path, user_path: Path | None = None) -> tuple[Location, Path] | None:
    """The first folder, in search order, that holds every executable of `spec`, and the first executable there."""
    names = [file_name(name) for name in spec.executables]
    for location, folder in _candidates(spec, tools_dir, user_path):
        if all((folder / name).is_file() for name in names):
            return location, folder / names[0]
    return None


def detect(
    spec: DependencySpec,
    tools_dir: Path,
    user_path: Path | None = None,
    cancel: threading.Event | None = None,
) -> DependencyStatus:
    found = locate(spec, tools_dir, user_path)
    if found is None:
        return DependencyStatus(spec.id, State.MISSING)
    location, path = found
    if spec.version_args is None:
        return DependencyStatus(spec.id, State.FOUND, path, location)
    try:
        result = run([path, *spec.version_args], timeout=VERSION_TIMEOUT_SECONDS, cancel=cancel)
    except ProcessError as error:
        return DependencyStatus(spec.id, State.BROKEN, path, location, detail=str(error))
    version = parse_version(spec, result.output)
    if version is None:
        return DependencyStatus(spec.id, State.BROKEN, path, location, detail=result.output.strip())
    if spec.min_version is not None and version_key(version) < version_key(spec.min_version):
        return DependencyStatus(spec.id, State.OUTDATED, path, location, version)
    return DependencyStatus(spec.id, State.FOUND, path, location, version)


def missing_for(
    feature: Feature, statuses: Mapping[str, DependencyStatus], specs: Iterable[DependencySpec] = SPECS
) -> list[DependencySpec]:
    """The programs that `feature` needs and that are not usable; an empty list means the feature is available.
    An outdated program counts as missing: the features were written against the minimum version."""
    return [
        spec
        for spec in specs
        if feature in spec.features and (spec.id not in statuses or statuses[spec.id].state is not State.FOUND)
    ]


def is_available(feature: Feature, statuses: Mapping[str, DependencyStatus]) -> bool:
    """Whether every program the feature needs was found. Not called yet; features that need an external program
    gate themselves on it."""
    return not missing_for(feature, statuses)
