"""Downloading a program from its official source and putting it into the app's tools folder.

Everything happens in a staging folder beside the target; the program's folder is swapped in only once
every file is downloaded, verified and unpacked, so a failed or cancelled install leaves the previous state.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any

from showrunner.tools.dependencies.http import Http, InsecureUrlError, require_https
from showrunner.tools.dependencies.specs import Archive, DependencySpec, GitHubRelease, IndexedRelease, Variant
from showrunner.tools.process import ProcessError, run

_CHUNK = 1 << 20
_INDEX_LIMIT = 8 << 20
_INSTALLERS = ".installers"
_SAFE_NAME = re.compile(r"[\w.\-]+")

# Bytes done so far and the total, when the source announces sizes.
type Progress = Callable[[int, int | None], None]


class InstallError(Exception):
    """A download or install failed; the tools folder is as it was before."""


class InstallCancelledError(InstallError):
    pass


class DigestMismatchError(InstallError):
    """The downloaded file is not the one the source published."""


class UnsafeArchiveError(InstallError):
    """An archive entry would land outside the folder it is unpacked into."""


@dataclass(frozen=True, slots=True)
class Asset:
    url: str
    name: str
    size: int | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    spec_id: str
    variant: Variant
    version: str
    assets: tuple[Asset, ...]

    @property
    def total_size(self) -> int | None:
        sizes = [asset.size for asset in self.assets]
        return None if None in sizes else sum(s for s in sizes if s is not None)


def find_variant(spec: DependencySpec, variant_id: str | None = None) -> Variant:
    variants = spec.source.variants
    if variant_id is None:
        return variants[0]
    for variant in variants:
        if variant.id == variant_id:
            return variant
    raise InstallError(f"{spec.id} has no build {variant_id!r}")


def resolve(spec: DependencySpec, variant: Variant, http: Http) -> DownloadPlan:
    """The newest files of `variant` with their sizes and checksums, as the source publishes them."""
    try:
        if isinstance(spec.source, GitHubRelease):
            return _resolve_github(spec, spec.source, variant, http)
        return _resolve_indexed(spec, spec.source, variant, http)
    except InstallError:
        raise
    except (OSError, HTTPException, ValueError, KeyError, TypeError) as error:
        raise InstallError(f"could not read the release list: {error}") from error


def _resolve_github(spec: DependencySpec, source: GitHubRelease, variant: Variant, client: Http) -> DownloadPlan:
    url = f"https://api.github.com/repos/{source.repo}/releases?per_page=30"
    releases: list[dict[str, Any]] = json.loads(client.fetch(url, _INDEX_LIMIT))
    allowed_prefix = f"https://github.com/{source.repo}/releases/download/"
    # The list is newest first; the first release that has every file of the variant wins.
    for release in releases:
        if release.get("draft") or (release.get("prerelease") and not source.prerelease):
            continue
        assets: list[Asset] = []
        for pattern in variant.patterns:
            entry = next((a for a in release.get("assets", []) if re.fullmatch(pattern, str(a.get("name")))), None)
            if entry is None:
                break
            download_url = str(entry["browser_download_url"])
            if not download_url.startswith(allowed_prefix):
                raise InstallError(f"{download_url} is not a release file of {source.repo}")
            digest = entry.get("digest")
            sha256 = (
                digest.removeprefix("sha256:") if isinstance(digest, str) and digest.startswith("sha256:") else None
            )
            assets.append(Asset(download_url, str(entry["name"]), int(entry["size"]), sha256))
        else:
            return DownloadPlan(spec.id, variant, str(release["tag_name"]), tuple(assets))
    raise InstallError(f"no release of {source.repo} has the files of build {variant.id!r}")


def _resolve_indexed(spec: DependencySpec, source: IndexedRelease, variant: Variant, client: Http) -> DownloadPlan:
    index: Any = json.loads(client.fetch(source.index_url, _INDEX_LIMIT))
    for key in source.version_keys:
        index = index[key]
    version = str(index)
    # The version becomes part of a URL, so only a plain version number is accepted.
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        raise InstallError(f"unexpected version {version!r} in {source.index_url}")
    url = source.url_template.format(version=version)
    name = url.rsplit("/", 1)[1]
    if not any(re.fullmatch(pattern, name) for pattern in variant.patterns):
        raise InstallError(f"{name} does not match build {variant.id!r}")
    sums = client.fetch(source.sums_template.format(version=version), _INDEX_LIMIT).decode("utf-8", "replace")
    sha256 = next((line.split()[0] for line in sums.splitlines() if line.split()[1:] == [name]), None)
    if sha256 is None:
        raise InstallError(f"{name} is not listed in the published checksums")
    return DownloadPlan(spec.id, variant, version, (Asset(url, name, None, sha256),))


def install(
    spec: DependencySpec,
    plan: DownloadPlan,
    tools_dir: Path,
    http: Http,
    progress: Progress,
    cancel: threading.Event,
) -> Path:
    """Download, verify and unpack `plan` into `<tools_dir>/<spec id>`, replacing what was there."""
    if plan.variant.archive is Archive.INSTALLER:
        raise InstallError(f"{spec.id} ships as an installer")
    with _staging(tools_dir, spec.id) as staging:
        files = _download_all(plan, staging / "downloads", http, progress, cancel)
        content = staging / "content"
        content.mkdir()
        for index, file in enumerate(files):
            unpacked = staging / f"unpacked{index}"
            _extract(file, plan.variant.archive, unpacked, cancel)
            _merge(_content_root(unpacked), content)
        target = tools_dir / spec.id
        previous = staging / "previous"
        try:
            if target.exists():
                os.replace(target, previous)
            try:
                os.replace(content, target)
            except OSError:
                if previous.exists():
                    os.replace(previous, target)
                raise
        except OSError as error:
            raise InstallError(f"could not replace {target}; is the program running? ({error})") from error
        return target


def download_installer(
    spec: DependencySpec,
    plan: DownloadPlan,
    tools_dir: Path,
    http: Http,
    progress: Progress,
    cancel: threading.Event,
) -> Path:
    """Download and verify an installer. Starting it is left to the caller, after the user agrees."""
    if plan.variant.archive is not Archive.INSTALLER or len(plan.assets) != 1:
        raise InstallError(f"{spec.id} does not ship as a single installer")
    folder = tools_dir / _INSTALLERS
    folder.mkdir(parents=True, exist_ok=True)
    # Earlier installers are of no further use; one still running cannot be deleted and is skipped.
    for old in folder.iterdir():
        try:
            old.unlink()
        except OSError:
            continue
    with _staging(tools_dir, spec.id) as staging:
        (file,) = _download_all(plan, staging, http, progress, cancel)
        target = folder / file.name
        os.replace(file, target)
        return target


@contextlib.contextmanager
def _staging(tools_dir: Path, spec_id: str) -> Iterator[Path]:
    """A fresh folder beside the target, removed with everything in it on the way out."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    prefix = f".install-{spec_id}-"
    # A staging folder left by a crash or a power cut is cleared before the next attempt.
    for leftover in tools_dir.glob(prefix + "*"):
        shutil.rmtree(leftover, ignore_errors=True)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=tools_dir))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _download_all(
    plan: DownloadPlan, folder: Path, client: Http, progress: Progress, cancel: threading.Event
) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    total = plan.total_size
    done = 0

    def advance(count: int) -> None:
        nonlocal done
        done += count
        progress(done, total)

    progress(0, total)
    return [_download(asset, folder, client, advance, cancel) for asset in plan.assets]


def _download(
    asset: Asset, folder: Path, client: Http, advance: Callable[[int], None], cancel: threading.Event
) -> Path:
    if not _SAFE_NAME.fullmatch(asset.name):
        raise InstallError(f"unexpected file name {asset.name!r}")
    target = folder / asset.name
    digest = hashlib.sha256()
    received = 0
    try:
        require_https(asset.url)
        with client.stream(asset.url) as response, target.open("wb") as out:
            require_https(response.url)
            expected = asset.size if asset.size is not None else response.length
            while chunk := response.read(_CHUNK):
                if cancel.is_set():
                    raise InstallCancelledError("cancelled")
                received += len(chunk)
                if expected is not None and received > expected:
                    raise InstallError(f"{asset.name} is larger than the announced {expected} bytes")
                out.write(chunk)
                digest.update(chunk)
                advance(len(chunk))
    except InsecureUrlError as error:
        raise InstallError(f"refused a download that is not HTTPS: {error}") from error
    except (OSError, HTTPException) as error:
        raise InstallError(f"download of {asset.name} failed: {error}") from error
    if cancel.is_set():
        raise InstallCancelledError("cancelled")
    if expected is not None and received != expected:
        raise InstallError(f"download of {asset.name} stopped after {received} of {expected} bytes")
    if asset.sha256 is not None and digest.hexdigest() != asset.sha256.lower():
        raise DigestMismatchError(f"{asset.name} does not match its published SHA-256")
    return target


def _checked_target(dest: Path, name: str) -> Path:
    """The path an archive entry unpacks to; an entry that would leave `dest` rejects the whole archive."""
    root = dest.resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise UnsafeArchiveError(f"archive entry {name!r} points outside the folder")
    return target


def _extract(archive: Path, kind: Archive, dest: Path, cancel: threading.Event) -> None:
    dest.mkdir(parents=True)
    if kind is Archive.ZIP:
        _extract_zip(archive, dest, cancel)
    elif kind is Archive.SEVEN_ZIP:
        _extract_7z(archive, dest, cancel)
    else:
        raise InstallError(f"{archive.name} is not an archive")


def _extract_zip(archive: Path, dest: Path, cancel: threading.Event) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            members = zf.infolist()
            for member in members:
                _checked_target(dest, member.filename)
            for member in members:
                if cancel.is_set():
                    raise InstallCancelledError("cancelled")
                zf.extract(member, dest)
    except zipfile.BadZipFile as error:
        raise InstallError(f"{archive.name} is not a valid zip archive: {error}") from error


def tar_program() -> Path:
    """The tar that ships with Windows, built on libarchive, which also reads 7z archives."""
    return Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "tar.exe"


def _extract_7z(archive: Path, dest: Path, cancel: threading.Event) -> None:
    tar = tar_program()
    try:
        listing = run([tar, "-tf", archive], cancel=cancel, check=True)
        for name in listing.stdout.splitlines():
            if name:
                _checked_target(dest, name)
        run([tar, "-xf", archive, "-C", dest], cancel=cancel, check=True)
    except ProcessError as error:
        if cancel.is_set():
            raise InstallCancelledError("cancelled") from error
        raise InstallError(f"could not unpack {archive.name}: {error}") from error
    # Links are not part of any program this app installs, and one could point anywhere.
    for path in dest.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise UnsafeArchiveError(f"archive entry {path.name!r} is a link")


def _content_root(folder: Path) -> Path:
    """Most archives wrap everything in one top folder named after the release; that folder is dropped."""
    entries = list(folder.iterdir())
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else folder


def _merge(source: Path, target: Path) -> None:
    target.mkdir(exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir() and destination.is_dir():
            _merge(child, destination)
        else:
            os.replace(child, destination)
