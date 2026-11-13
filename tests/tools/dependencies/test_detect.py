from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from showrunner.tools.dependencies import detect as detect_module
from showrunner.tools.dependencies.detect import (
    DependencyStatus,
    Location,
    State,
    detect,
    file_name,
    is_available,
    locate,
    missing_for,
    parse_version,
    version_key,
)
from showrunner.tools.dependencies.specs import SPEC_BY_ID, SPECS, DependencySpec, Feature
from showrunner.tools.process import ProcessTimeoutError, RunResult


@pytest.mark.parametrize(
    ("spec_id", "output", "version"),
    [
        ("mkvtoolnix", "mkvmerge v103.0 ('The Darkness') 64-bit", "103.0"),
        ("ffmpeg", "ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026", "9.0.2"),
        ("ffmpeg", "ffmpeg version n9.0-12-gabc Copyright", "9.0"),
        ("ffmpeg", "ffmpeg version N-121000-gabcdef Copyright", None),
        ("tesseract", "tesseract v5.4.0.20240606\n leptonica-1.84.1", "5.4.0.20240606"),
        ("ollama", "ollama version is 0.40.16", "0.40.16"),
        (
            "ollama",
            "Warning: could not connect to a running Ollama instance\nWarning: client version is 0.40.16",
            "0.40.16",
        ),
        ("llama_cpp", "version: 12366 (1a2b3c4)\nbuilt with MSVC", "12366"),
        ("alass", "alass-cli 2.0.0", "2.0.0"),
        ("lapse", "lapse 2.5.0", "2.5.0"),
        ("mkvtoolnix", "something else entirely", None),
    ],
)
def test_version_parsing(spec_id: str, output: str, version: str | None) -> None:
    assert parse_version(SPEC_BY_ID[spec_id], output) == version


def test_version_order_is_numeric() -> None:
    assert version_key("10.0") > version_key("9.12")
    assert version_key("5.4.0.20240606") > version_key("5.0")


def test_every_spec_is_complete() -> None:
    for spec in SPECS:
        assert spec.official_url.startswith("https://")
        assert spec.executables
        assert spec.features
        assert spec.source.variants
        assert (spec.version_args is None) == (spec.version_pattern is None)


def touch(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / file_name(name)).write_bytes(b"")
    return folder


@pytest.fixture
def places(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A user folder, the tools folder, a PATH folder and an install folder, all empty to start with."""
    folders = {name: tmp_path / name for name in ("user", "tools", "path", "install")}
    monkeypatch.setenv("PATH", str(folders["path"]))
    monkeypatch.setenv("SHOWRUNNER_TEST_INSTALL", str(folders["install"]))
    return folders


def spec_with_install_dir(spec_factory: Callable[..., DependencySpec], **kwargs: Any) -> DependencySpec:
    return spec_factory(install_dirs=("%SHOWRUNNER_TEST_INSTALL%", "%SHOWRUNNER_UNSET_VARIABLE%"), **kwargs)


def test_resolution_order(places: dict[str, Path], spec_factory: Callable[..., DependencySpec]) -> None:
    spec = spec_with_install_dir(spec_factory)
    tools = places["tools"]
    touch(places["install"], "tool")
    assert locate(spec, tools) == (Location.INSTALL_DIR, places["install"] / file_name("tool"))
    touch(places["path"], "tool")
    assert locate(spec, tools)[0] is Location.PATH  # type: ignore[index]
    touch(tools / "tool" / "bin", "tool")
    assert locate(spec, tools) == (Location.TOOLS, tools / "tool" / "bin" / file_name("tool"))
    user_file = touch(places["user"], "tool") / file_name("tool")
    assert locate(spec, tools, user_file) == (Location.USER, user_file)
    # A folder works as well as the file itself.
    assert locate(spec, tools, places["user"]) == (Location.USER, user_file)


def test_a_user_path_without_the_program_falls_back_to_searching(places: dict[str, Path], spec: DependencySpec) -> None:
    touch(places["path"], "tool")
    assert locate(spec, places["tools"], places["user"])[0] is Location.PATH  # type: ignore[index]


def test_every_executable_must_be_in_the_same_folder(
    places: dict[str, Path], spec_factory: Callable[..., DependencySpec]
) -> None:
    spec = spec_with_install_dir(spec_factory, executables=("tool", "helper"))
    touch(places["path"], "tool")
    touch(places["install"], "tool", "helper")
    assert locate(spec, places["tools"]) == (Location.INSTALL_DIR, places["install"] / file_name("tool"))


@pytest.fixture
def version_output(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | Exception], None]:
    """Replaces running the program with a fixed output, or with an error."""

    def set_output(output: str | Exception) -> None:
        def fake_run(args: list[Any], **_: Any) -> RunResult:
            if isinstance(output, Exception):
                raise output
            return RunResult(tuple(map(str, args)), 0, output, "")

        monkeypatch.setattr(detect_module, "run", fake_run)

    return set_output


def test_status_found(places: dict[str, Path], spec: DependencySpec, version_output: Any) -> None:
    touch(places["path"], "tool")
    version_output("tool v2.1.0")
    status = detect(spec, places["tools"])
    assert status == DependencyStatus("tool", State.FOUND, places["path"] / file_name("tool"), Location.PATH, "2.1.0")
    assert status.executable("tool") == places["path"] / file_name("tool")


def test_status_outdated(places: dict[str, Path], spec: DependencySpec, version_output: Any) -> None:
    touch(places["path"], "tool")
    version_output("tool v1.9")
    assert detect(spec, places["tools"]).state is State.OUTDATED


def test_status_broken_when_no_version_is_printed(
    places: dict[str, Path], spec: DependencySpec, version_output: Any
) -> None:
    touch(places["path"], "tool")
    version_output("usage: tool [options]")
    status = detect(spec, places["tools"])
    assert status.state is State.BROKEN
    assert status.detail == "usage: tool [options]"


def test_status_broken_when_it_does_not_run(places: dict[str, Path], spec: DependencySpec, version_output: Any) -> None:
    touch(places["path"], "tool")
    version_output(ProcessTimeoutError("no result", ["tool"]))
    assert detect(spec, places["tools"]).state is State.BROKEN


def test_status_missing(places: dict[str, Path], spec: DependencySpec) -> None:
    assert detect(spec, places["tools"]) == DependencyStatus("tool", State.MISSING)


def test_a_library_is_found_without_running_it(
    places: dict[str, Path], spec_factory: Callable[..., DependencySpec]
) -> None:
    spec = spec_factory(executables=("libthing.dll",), version_args=None)
    touch(places["path"], "libthing.dll")
    status = detect(spec, places["tools"])
    assert status.state is State.FOUND
    assert status.path == places["path"] / "libthing.dll"


def test_capability_query() -> None:
    def status(spec_id: str, state: State) -> DependencyStatus:
        return DependencyStatus(spec_id, state)

    statuses = {
        "mkvtoolnix": status("mkvtoolnix", State.FOUND),
        "tesseract": status("tesseract", State.MISSING),
        "ffmpeg": status("ffmpeg", State.OUTDATED),
    }
    assert is_available(Feature.MUX, statuses)
    assert [s.id for s in missing_for(Feature.OCR, statuses)] == ["tesseract"]
    assert [s.id for s in missing_for(Feature.PROBE_MEDIA, statuses)] == ["ffmpeg"]
    # A program that was never checked counts as missing.
    assert [s.id for s in missing_for(Feature.PLAYER, statuses)] == ["libmpv"]


def test_a_feature_needing_two_programs_lists_each_missing_one(spec_factory: Callable[..., DependencySpec]) -> None:
    first = spec_factory(spec_id="a", features=(Feature.SYNC_LAPSE,))
    second = spec_factory(spec_id="b", features=(Feature.SYNC_LAPSE,))
    statuses = {"a": DependencyStatus("a", State.FOUND), "b": DependencyStatus("b", State.BROKEN)}
    assert missing_for(Feature.SYNC_LAPSE, statuses, [first, second]) == [second]
