from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from showrunner.app.ai import AI
from showrunner.app.dependencies import service
from showrunner.app.settings.app_settings import load_settings
from showrunner.app.storage.paths import HOME_ENV_VAR, tools_dir
from showrunner.tools.ai import OllamaBackend
from showrunner.tools.dependencies import detect as detect_module
from showrunner.tools.dependencies import install as install_module
from showrunner.tools.dependencies.detect import DependencyStatus, State, file_name
from showrunner.tools.dependencies.install import Asset, DownloadPlan
from showrunner.tools.dependencies.specs import SPEC_BY_ID


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    monkeypatch.setenv("PATH", "")
    return tmp_path


def test_user_paths_are_kept_with_the_app_settings(home: Path) -> None:
    service.set_user_path("libmpv", home / "mpv" / "libmpv-2.dll")
    assert load_settings().value.tool_paths == {"libmpv": str(home / "mpv" / "libmpv-2.dll")}
    assert service.user_path("libmpv") == home / "mpv" / "libmpv-2.dll"
    service.set_user_path("libmpv", None)
    assert load_settings().value.tool_paths == {}
    assert service.user_path("libmpv") is None


def test_a_user_path_is_used_for_checking(home: Path) -> None:
    folder = home / "elsewhere"
    folder.mkdir()
    (folder / "libmpv-2.dll").write_bytes(b"")
    assert service.check(SPEC_BY_ID["libmpv"]).state is State.MISSING
    service.set_user_path("libmpv", folder)
    assert service.check(SPEC_BY_ID["libmpv"]).path == folder / "libmpv-2.dll"


def test_installing_puts_the_program_in_the_tools_folder_and_clears_the_user_path(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = SPEC_BY_ID["libmpv"]
    service.set_user_path("libmpv", home / "gone")

    def fake_install(spec_arg: object, plan: object, tools: Path, *_: object) -> Path:
        (tools / "libmpv").mkdir(parents=True)
        (tools / "libmpv" / "libmpv-2.dll").write_bytes(b"")
        return tools / "libmpv"

    monkeypatch.setattr(install_module, "install", fake_install)
    plan = DownloadPlan("libmpv", spec.source.variants[0], "1", (Asset("https://x/y.7z", "y.7z", 1, None),))
    status = service.install(plan, lambda *_: None, threading.Event(), http=object())  # type: ignore[arg-type]
    assert status.state is State.FOUND
    assert status.path == tools_dir() / "libmpv" / "libmpv-2.dll"
    assert service.user_path("libmpv") is None


def test_media_programs_use_only_programs_that_are_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.FOUND, Path("mkv/mkvmerge.exe")),
        "ffmpeg": DependencyStatus("ffmpeg", State.OUTDATED, Path("ff/ffmpeg.exe"), version="5.0"),
    }
    monkeypatch.setattr(service, "check", lambda spec, cancel=None: statuses[spec.id])
    programs = service.media_programs()
    assert programs.mkvmerge == Path("mkv/mkvmerge.exe")
    # Its sibling is named the way programs are on this system.
    assert programs.mkvextract == Path("mkv") / file_name("mkvextract")
    assert programs.ffprobe is None


class VersionServer:
    """Stands in for Ollama's server: answers `/api/version` with `version`, or nothing at all when it is None."""

    def __init__(self, version: str | None) -> None:
        answer = version

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                data = json.dumps({"version": answer}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        if version is None:
            self.http.server_close()  # nothing listens at the address
        else:
            threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self) -> None:
        if self.http.socket.fileno() != -1:
            self.http.shutdown()
            self.http.server_close()


@pytest.fixture
def ollama(home: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str | None], None]]:
    # Not this machine's own install folder.
    monkeypatch.setenv("LOCALAPPDATA", str(home / "local"))
    servers: list[VersionServer] = []

    def serve(version: str | None) -> None:
        servers.append(VersionServer(version))
        monkeypatch.setattr(AI, "backend", OllamaBackend(servers[-1].url))

    yield serve
    for server in servers:
        server.close()


def test_ollama_is_never_run_its_state_comes_from_its_server(
    home: Path, ollama: Callable[[str | None], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the ollama command starts the desktop app on Windows")

    monkeypatch.setattr(detect_module, "run", never)
    spec = SPEC_BY_ID["ollama"]
    ollama(None)
    assert service.check(spec).state is State.MISSING
    program = tools_dir() / "ollama" / file_name("ollama")
    program.parent.mkdir(parents=True)
    program.write_bytes(b"")
    stopped = service.check(spec)
    # Installed, so Locate and Download act on the file found, but its server does not answer.
    assert (stopped.state, stopped.path, stopped.version) == (State.STOPPED, program, None)
    ollama("0.40.17")
    running = service.check(spec)
    assert (running.state, running.path, running.version) == (State.FOUND, program, "0.40.17")
    ollama("0.4.0")
    assert service.check(spec).state is State.OUTDATED


def test_a_server_that_answers_counts_where_no_program_file_is_found(ollama: Callable[[str | None], None]) -> None:
    ollama("0.40.17")
    found = service.check(SPEC_BY_ID["ollama"])
    assert (found.state, found.path, found.version) == (State.FOUND, None, "0.40.17")
