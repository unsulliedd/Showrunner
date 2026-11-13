from __future__ import annotations

import contextlib
import hashlib
import io
import json
import threading
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from showrunner.tools.dependencies import install as install_module
from showrunner.tools.dependencies.http import InsecureUrlError, _HttpsOnlyRedirects, require_https
from showrunner.tools.dependencies.install import (
    Asset,
    DigestMismatchError,
    DownloadPlan,
    InstallCancelledError,
    InstallError,
    UnsafeArchiveError,
    download_installer,
    find_variant,
    install,
    resolve,
    tar_program,
)
from showrunner.tools.dependencies.specs import SPEC_BY_ID, Archive, DependencySpec, Variant
from showrunner.tools.process import RunResult, run

RELEASES_URL = "https://api.github.com/repos/owner/tool/releases?per_page=30"
DOWNLOAD = "https://github.com/owner/tool/releases/download/"


class FakeResponse:
    """Hands out a few bytes per read, so a download takes several chunks; can fail part-way."""

    def __init__(self, url: str, data: bytes, fail_after: int | None) -> None:
        self.url = url
        self.length: int | None = len(data)
        self._data = io.BytesIO(data)
        self._fail_after = fail_after

    def read(self, size: int = -1, /) -> bytes:
        if self._fail_after is not None and self._data.tell() >= self._fail_after:
            raise ConnectionResetError("connection reset")
        return self._data.read(4)


class FakeHttp:
    def __init__(self) -> None:
        self.documents: dict[str, bytes] = {}
        self.files: dict[str, bytes] = {}
        self.fail_after: int | None = None
        self.final_url: dict[str, str] = {}
        self.streamed: list[str] = []

    def fetch(self, url: str, limit: int) -> bytes:
        return self.documents[url]

    @contextlib.contextmanager
    def stream(self, url: str) -> Iterator[FakeResponse]:
        self.streamed.append(url)
        yield FakeResponse(self.final_url.get(url, url), self.files[url], self.fail_after)


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_for(spec: DependencySpec, files: dict[str, bytes], http: FakeHttp, **overrides: Any) -> DownloadPlan:
    assets = []
    for name, data in files.items():
        url = DOWNLOAD + "v2.0/" + name
        http.files[url] = data
        values = {"url": url, "name": name, "size": len(data), "sha256": sha(data)} | overrides
        assets.append(Asset(**values))
    return DownloadPlan(spec.id, spec.source.variants[0], "v2.0", tuple(assets))


def leftovers(tools: Path) -> list[str]:
    return sorted(p.name for p in tools.iterdir()) if tools.exists() else []


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None]] = []

    def __call__(self, done: int, total: int | None) -> None:
        self.calls.append((done, total))


# Resolving a release


def asset_entry(name: str, size: int = 10, digest: str | None = "sha256:ab12") -> dict[str, Any]:
    return {"name": name, "size": size, "digest": digest, "browser_download_url": DOWNLOAD + "x/" + name}


def test_resolve_picks_the_newest_matching_release(spec: DependencySpec) -> None:
    http = FakeHttp()
    http.documents[RELEASES_URL] = json.dumps(
        [
            {"tag_name": "v3.0-draft", "draft": True, "assets": [asset_entry("tool-3.0-win.zip")]},
            {"tag_name": "v3.0-rc1", "prerelease": True, "assets": [asset_entry("tool-3.0-win.zip")]},
            {"tag_name": "v2.1", "assets": [asset_entry("notes.txt")]},
            {"tag_name": "v2.0", "assets": [asset_entry("tool-2.0-linux.tar.gz"), asset_entry("tool-2.0-win.zip")]},
        ]
    ).encode()
    plan = resolve(spec, find_variant(spec), http)
    assert plan.version == "v2.0"
    assert plan.assets == (Asset(DOWNLOAD + "x/tool-2.0-win.zip", "tool-2.0-win.zip", 10, "ab12"),)


def test_resolve_takes_pre_releases_when_the_spec_allows_them(spec_factory: Callable[..., DependencySpec]) -> None:
    spec = spec_factory(prerelease=True)
    http = FakeHttp()
    http.documents[RELEASES_URL] = json.dumps(
        [{"tag_name": "b123", "prerelease": True, "assets": [asset_entry("tool-1.2-win.zip", digest=None)]}]
    ).encode()
    plan = resolve(spec, find_variant(spec), http)
    assert plan.version == "b123"
    assert plan.assets[0].sha256 is None


def test_resolve_refuses_files_outside_the_projects_releases(spec: DependencySpec) -> None:
    entry = asset_entry("tool-2.0-win.zip") | {"browser_download_url": "https://elsewhere.example/tool-2.0-win.zip"}
    http = FakeHttp()
    http.documents[RELEASES_URL] = json.dumps([{"tag_name": "v2.0", "assets": [entry]}]).encode()
    with pytest.raises(InstallError):
        resolve(spec, find_variant(spec), http)


def test_resolve_reports_a_release_list_it_cannot_read(spec: DependencySpec) -> None:
    http = FakeHttp()
    http.documents[RELEASES_URL] = b"<html>rate limited</html>"
    with pytest.raises(InstallError):
        resolve(spec, find_variant(spec), http)


def mkvtoolnix_http(version: str, listed: str) -> FakeHttp:
    http = FakeHttp()
    index = {"mkvtoolnix-releases": {"latest-source": {"version": version}}}
    http.documents["https://mkvtoolnix.download/latest-release.json"] = json.dumps(index).encode()
    sums = f"{'1' * 64}  mkvtoolnix-64-bit-{version}-setup.exe\n{'2' * 64}  {listed}\n"
    http.documents[f"https://mkvtoolnix.download/windows/releases/{version}/sha256sums.txt"] = sums.encode()
    return http


def test_resolve_an_indexed_release() -> None:
    spec = SPEC_BY_ID["mkvtoolnix"]
    plan = resolve(spec, find_variant(spec), mkvtoolnix_http("103.0", "mkvtoolnix-64-bit-103.0.zip"))
    assert plan.version == "103.0"
    assert plan.assets == (
        Asset(
            "https://mkvtoolnix.download/windows/releases/103.0/mkvtoolnix-64-bit-103.0.zip",
            "mkvtoolnix-64-bit-103.0.zip",
            None,
            "2" * 64,
        ),
    )


def test_an_indexed_release_needs_a_published_checksum() -> None:
    spec = SPEC_BY_ID["mkvtoolnix"]
    with pytest.raises(InstallError):
        resolve(spec, find_variant(spec), mkvtoolnix_http("103.0", "mkvtoolnix-64-bit-103.0.7z"))


def test_an_indexed_version_must_be_a_plain_number() -> None:
    spec = SPEC_BY_ID["mkvtoolnix"]
    with pytest.raises(InstallError):
        resolve(spec, find_variant(spec), mkvtoolnix_http("1/../../x", "anything"))


def test_unknown_build_is_an_error(spec: DependencySpec) -> None:
    with pytest.raises(InstallError):
        find_variant(spec, "nope")


# Installing


def test_install_unpacks_verified_files_and_drops_the_top_folder(tmp_path: Path, spec: DependencySpec) -> None:
    http = FakeHttp()
    data = zip_bytes({"tool-2.0/bin/tool.exe": b"program", "tool-2.0/readme.txt": b"hi"})
    plan = plan_for(spec, {"tool-2.0-win.zip": data}, http)
    progress = Recorder()
    target = install(spec, plan, tmp_path / "tools", http, progress, threading.Event())
    assert target == tmp_path / "tools" / "tool"
    assert (target / "bin" / "tool.exe").read_bytes() == b"program"
    assert leftovers(tmp_path / "tools") == ["tool"]
    assert progress.calls[0] == (0, len(data))
    assert progress.calls[-1] == (len(data), len(data))


def test_install_replaces_the_previous_copy(tmp_path: Path, spec: DependencySpec) -> None:
    tools = tmp_path / "tools"
    (tools / "tool").mkdir(parents=True)
    (tools / "tool" / "old.txt").write_text("old")
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"new"})}, http)
    install(spec, plan, tools, http, Recorder(), threading.Event())
    assert sorted(p.name for p in (tools / "tool").iterdir()) == ["tool.exe"]
    assert leftovers(tools) == ["tool"]


def test_files_of_every_asset_land_in_one_folder(tmp_path: Path, spec_factory: Callable[..., DependencySpec]) -> None:
    spec = spec_factory(variants=(Variant("gpu", (r"tool-.*\.zip", r"runtime-.*\.zip"), Archive.ZIP),))
    http = FakeHttp()
    files = {
        "tool-2.0-win.zip": zip_bytes({"tool.exe": b"t", "lib/a.dll": b"a"}),
        "runtime-2.0.zip": zip_bytes({"runtime.dll": b"r", "lib/b.dll": b"b"}),
    }
    target = install(spec, plan_for(spec, files, http), tmp_path / "tools", http, Recorder(), threading.Event())
    assert sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()) == [
        "lib/a.dll",
        "lib/b.dll",
        "runtime.dll",
        "tool.exe",
    ]


@pytest.mark.parametrize("evil", ["../escaped.txt", "sub/../../escaped.txt", "/abs/escaped.txt", "C:/escaped.txt"])
def test_zip_slip_is_rejected_and_nothing_is_written(tmp_path: Path, spec: DependencySpec, evil: str) -> None:
    tools = tmp_path / "data" / "tools"
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"ok", evil: b"bad"})}, http)
    with pytest.raises(UnsafeArchiveError):
        install(spec, plan, tools, http, Recorder(), threading.Event())
    assert leftovers(tools) == []
    assert not list(tmp_path.rglob("escaped.txt"))


def test_an_interrupted_download_leaves_nothing_behind(tmp_path: Path, spec: DependencySpec) -> None:
    tools = tmp_path / "tools"
    (tools / "tool").mkdir(parents=True)
    (tools / "tool" / "tool.exe").write_bytes(b"previous")
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"new" * 100})}, http)
    http.fail_after = 40
    with pytest.raises(InstallError, match="connection reset"):
        install(spec, plan, tools, http, Recorder(), threading.Event())
    assert leftovers(tools) == ["tool"]
    assert (tools / "tool" / "tool.exe").read_bytes() == b"previous"


def test_a_cancelled_download_leaves_nothing_behind(tmp_path: Path, spec: DependencySpec) -> None:
    tools = tmp_path / "tools"
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"new" * 100})}, http)
    cancel = threading.Event()

    def cancel_after_some_bytes(done: int, total: int | None) -> None:
        if done >= 20:
            cancel.set()

    with pytest.raises(InstallCancelledError):
        install(spec, plan, tools, http, cancel_after_some_bytes, cancel)
    assert leftovers(tools) == []


def test_a_digest_mismatch_is_rejected(tmp_path: Path, spec: DependencySpec) -> None:
    tools = tmp_path / "tools"
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"x"})}, http, sha256="0" * 64)
    with pytest.raises(DigestMismatchError):
        install(spec, plan, tools, http, Recorder(), threading.Event())
    assert leftovers(tools) == []


@pytest.mark.parametrize("announced", [5, 10_000])
def test_a_size_mismatch_is_rejected(tmp_path: Path, spec: DependencySpec, announced: int) -> None:
    tools = tmp_path / "tools"
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"x"})}, http, size=announced, sha256=None)
    with pytest.raises(InstallError):
        install(spec, plan, tools, http, Recorder(), threading.Event())
    assert leftovers(tools) == []


def test_plain_http_is_refused(tmp_path: Path, spec: DependencySpec) -> None:
    http = FakeHttp()
    data = zip_bytes({"tool.exe": b"x"})
    url = "http://github.com/owner/tool/releases/download/v2.0/tool-2.0-win.zip"
    http.files[url] = data
    plan = DownloadPlan(spec.id, spec.source.variants[0], "v2.0", (Asset(url, "tool-2.0-win.zip", len(data), None),))
    with pytest.raises(InstallError, match="HTTPS"):
        install(spec, plan, tmp_path / "tools", http, Recorder(), threading.Event())
    assert http.streamed == []


def test_a_redirect_to_plain_http_is_refused(tmp_path: Path, spec: DependencySpec) -> None:
    http = FakeHttp()
    plan = plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"x"})}, http)
    http.final_url[plan.assets[0].url] = "http://mirror.example/tool.zip"
    with pytest.raises(InstallError, match="HTTPS"):
        install(spec, plan, tmp_path / "tools", http, Recorder(), threading.Event())
    assert leftovers(tmp_path / "tools") == []


def test_the_real_client_refuses_redirects_to_plain_http() -> None:
    require_https("https://example.org/")
    request = urllib.request.Request("https://example.org/file")
    with pytest.raises(InsecureUrlError):
        _HttpsOnlyRedirects().redirect_request(request, None, 302, "Found", {}, "http://example.org/file")


def test_a_staging_folder_left_by_a_crash_is_cleared(tmp_path: Path, spec: DependencySpec) -> None:
    tools = tmp_path / "tools"
    (tools / ".install-tool-crashed").mkdir(parents=True)
    http = FakeHttp()
    install(
        spec,
        plan_for(spec, {"tool-2.0-win.zip": zip_bytes({"tool.exe": b"x"})}, http),
        tools,
        http,
        Recorder(),
        threading.Event(),
    )
    assert leftovers(tools) == ["tool"]


def test_an_installer_is_downloaded_verified_and_kept_for_the_user(
    tmp_path: Path, spec_factory: Callable[..., DependencySpec]
) -> None:
    spec = spec_factory(variants=(Variant("default", (r"tool-setup\.exe",), Archive.INSTALLER),))
    tools = tmp_path / "tools"
    (tools / ".installers").mkdir(parents=True)
    (tools / ".installers" / "older-setup.exe").write_bytes(b"old")
    http = FakeHttp()
    path = download_installer(
        spec, plan_for(spec, {"tool-setup.exe": b"MZ installer"}, http), tools, http, Recorder(), threading.Event()
    )
    assert path == tools / ".installers" / "tool-setup.exe"
    assert path.read_bytes() == b"MZ installer"
    assert leftovers(tools) == [".installers"]
    assert [p.name for p in (tools / ".installers").iterdir()] == ["tool-setup.exe"]


def test_an_installer_is_never_unpacked(tmp_path: Path, spec_factory: Callable[..., DependencySpec]) -> None:
    spec = spec_factory(variants=(Variant("default", (r"tool-setup\.exe",), Archive.INSTALLER),))
    http = FakeHttp()
    with pytest.raises(InstallError):
        install(spec, plan_for(spec, {"tool-setup.exe": b"MZ"}, http), tmp_path, http, Recorder(), threading.Event())


# 7z archives, unpacked by the tar that ships with Windows

needs_tar = pytest.mark.skipif(not tar_program().is_file(), reason="needs the tar that ships with Windows")


@needs_tar
def test_a_7z_archive_is_unpacked(tmp_path: Path, spec_factory: Callable[..., DependencySpec]) -> None:
    source = tmp_path / "source"
    (source / "mpv-dev" / "include").mkdir(parents=True)
    (source / "mpv-dev" / "libtool.dll").write_bytes(b"library")
    (source / "mpv-dev" / "include" / "client.h").write_text("header")
    archive = tmp_path / "tool.7z"
    run([tar_program(), "--format=7zip", "-cf", archive, "-C", source, "mpv-dev"], check=True)
    spec = spec_factory(variants=(Variant("default", (r"tool\.7z",), Archive.SEVEN_ZIP),))
    http = FakeHttp()
    plan = plan_for(spec, {"tool.7z": archive.read_bytes()}, http)
    target = install(spec, plan, tmp_path / "tools", http, Recorder(), threading.Event())
    assert (target / "libtool.dll").read_bytes() == b"library"
    assert (target / "include" / "client.h").read_text() == "header"


def test_a_7z_entry_escaping_the_folder_is_rejected_before_unpacking(
    tmp_path: Path, spec_factory: Callable[..., DependencySpec], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[Any], **_: Any) -> RunResult:
        calls.append([str(a) for a in args])
        return RunResult(tuple(calls[-1]), 0, "ok.dll\n../../escaped.dll\n", "")

    monkeypatch.setattr(install_module, "run", fake_run)
    spec = spec_factory(variants=(Variant("default", (r"tool\.7z",), Archive.SEVEN_ZIP),))
    http = FakeHttp()
    with pytest.raises(UnsafeArchiveError):
        install(spec, plan_for(spec, {"tool.7z": b"7z"}, http), tmp_path / "tools", http, Recorder(), threading.Event())
    assert [c[1] for c in calls] == ["-tf"]
    assert leftovers(tmp_path / "tools") == []
