"""External programs as the app sees them: searched with the user's own paths and installed into the data folder."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from showrunner.app.settings.app_settings import load_settings, save_settings
from showrunner.app.storage.paths import tools_dir
from showrunner.core.media import MediaFile
from showrunner.tools.dependencies import install as installer
from showrunner.tools.dependencies.detect import DependencyStatus, State, detect
from showrunner.tools.dependencies.http import Http, UrllibHttp
from showrunner.tools.dependencies.install import DownloadPlan, Progress
from showrunner.tools.dependencies.specs import SPEC_BY_ID, SPECS, DependencySpec
from showrunner.tools.probe import Programs, probe
from showrunner.tools.process import open_with_shell


def user_path(spec_id: str) -> Path | None:
    raw = load_settings().value.tool_paths.get(spec_id)
    return Path(raw) if raw else None


def set_user_path(spec_id: str, path: Path | None) -> None:
    """Remember where the user says a program is; None goes back to searching."""
    settings = load_settings().value
    paths = dict(settings.tool_paths)
    if path is None:
        paths.pop(spec_id, None)
    else:
        paths[spec_id] = str(path)
    save_settings(replace(settings, tool_paths=paths))


def check(spec: DependencySpec, cancel: threading.Event | None = None) -> DependencyStatus:
    return detect(spec, tools_dir(), user_path(spec.id), cancel)


def check_all(cancel: threading.Event | None = None) -> dict[str, DependencyStatus]:
    return {spec.id: check(spec, cancel) for spec in SPECS}


def plan_download(spec_id: str, variant_id: str | None = None, http: Http | None = None) -> DownloadPlan:
    spec = SPEC_BY_ID[spec_id]
    return installer.resolve(spec, installer.find_variant(spec, variant_id), http or UrllibHttp())


def install(
    plan: DownloadPlan, progress: Progress, cancel: threading.Event, http: Http | None = None
) -> DependencyStatus:
    """Install into the tools folder and check the result. A path the user set still wins over the
    fresh copy, so it is cleared: installing is the user choosing the app's own copy."""
    spec = SPEC_BY_ID[plan.spec_id]
    installer.install(spec, plan, tools_dir(), http or UrllibHttp(), progress, cancel)
    if user_path(spec.id) is not None:
        set_user_path(spec.id, None)
    return check(spec)


def download_installer(
    plan: DownloadPlan, progress: Progress, cancel: threading.Event, http: Http | None = None
) -> Path:
    return installer.download_installer(
        SPEC_BY_ID[plan.spec_id], plan, tools_dir(), http or UrllibHttp(), progress, cancel
    )


def start_installer(path: Path) -> None:
    open_with_shell(path)


def media_programs(cancel: threading.Event | None = None) -> Programs:
    """The programs that read media files, found the way the Dependencies page finds them. An outdated
    program counts as missing, like everywhere else."""
    mkvtoolnix = check(SPEC_BY_ID["mkvtoolnix"], cancel)
    ffmpeg = check(SPEC_BY_ID["ffmpeg"], cancel)
    usable_mkv = mkvtoolnix.state is State.FOUND
    usable_ffmpeg = ffmpeg.state is State.FOUND
    return Programs(
        mkvmerge=mkvtoolnix.path if usable_mkv else None,
        mkvextract=mkvtoolnix.executable("mkvextract") if usable_mkv else None,
        ffprobe=ffmpeg.executable("ffprobe") if usable_ffmpeg else None,
    )


def probe_file(path: Path, programs: Programs | None = None, cancel: threading.Event | None = None) -> MediaFile:
    """Read one file. Callers that read many files pass `programs` once instead of detecting for each."""
    return probe(path, programs or media_programs(cancel), cancel=cancel)
