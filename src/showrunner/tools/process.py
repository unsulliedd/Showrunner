"""The one way the app runs an external program: no console window, timeout, cancellation, decoded output."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# How often a waiting run checks for cancellation; short enough that Cancel feels immediate.
_POLL_SECONDS = 0.1
# Without this flag every console program started from the GUI flashes its own console window.
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass(frozen=True, slots=True)
class RunResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        """Standard output and standard error together; many programs print their version to either."""
        return f"{self.stdout}\n{self.stderr}" if self.stderr else self.stdout


class ProcessError(Exception):
    """A program could not be run to the end."""

    def __init__(self, message: str, args: Sequence[str]) -> None:
        super().__init__(message)
        self.command = tuple(args)


class ProgramNotFoundError(ProcessError):
    """The program file is missing or cannot be started."""


class ProcessTimeoutError(ProcessError):
    """The program ran longer than its timeout and was stopped."""


class ProcessCancelledError(ProcessError):
    """The run was cancelled and the program was stopped."""


class ProcessFailedError(ProcessError):
    """The program ended with a non-zero exit code."""

    def __init__(self, result: RunResult) -> None:
        super().__init__(f"exit code {result.returncode}", result.args)
        self.result = result


def run(
    args: Sequence[str | Path],
    *,
    timeout: float | None = None,
    cancel: threading.Event | None = None,
    check: bool = False,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RunResult:
    """Run a program to the end and capture its output, decoded as UTF-8 with bad bytes replaced.

    With `check`, a non-zero exit code raises ProcessFailedError. Stdin is closed, so a program that
    asks a question fails at once instead of waiting forever.
    """
    command = tuple(str(a) for a in args)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=None if env is None else dict(env),
            creationflags=_CREATION_FLAGS,
        )
    except OSError as error:
        raise ProgramNotFoundError(str(error), command) from error
    deadline = None if timeout is None else time.monotonic() + timeout
    with process:
        while True:
            try:
                out, err = process.communicate(timeout=_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _stop(process)
                    raise ProcessCancelledError("cancelled", command) from None
                if deadline is not None and time.monotonic() >= deadline:
                    _stop(process)
                    raise ProcessTimeoutError(f"no result after {timeout} s", command) from None
    result = RunResult(command, process.returncode, _decode(out), _decode(err))
    if check and result.returncode != 0:
        raise ProcessFailedError(result)
    return result


def open_with_shell(path: Path) -> None:
    """Start a file the way a double-click would, without waiting for it.

    Installers ask for administrator rights, which a plain process start cannot grant; the shell
    shows the elevation prompt instead.
    """
    if os.name != "nt":
        raise ProgramNotFoundError("starting an installer is supported on Windows only", [str(path)])
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    except OSError as error:
        raise ProgramNotFoundError(str(error), [str(path)]) from error


def _stop(process: subprocess.Popen[bytes]) -> None:
    process.kill()
    process.communicate()


def _decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")
