from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from showrunner.tools.process import (
    ProcessCancelledError,
    ProcessFailedError,
    ProcessTimeoutError,
    ProgramNotFoundError,
    run,
)


def python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_captures_both_streams_and_the_exit_code() -> None:
    result = run(python("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"))
    assert result.returncode == 3
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert "out" in result.output
    assert "err" in result.output


def test_output_is_utf8_with_bad_bytes_replaced() -> None:
    result = run(python("import sys; sys.stdout.buffer.write('Ünïcode '.encode() + b'\\xff')"))
    assert result.stdout == "Ünïcode �"


def test_check_raises_on_a_non_zero_exit() -> None:
    with pytest.raises(ProcessFailedError) as caught:
        run(python("raise SystemExit(2)"), check=True)
    assert caught.value.result.returncode == 2


def test_a_missing_program_raises_its_own_error(tmp_path: Path) -> None:
    with pytest.raises(ProgramNotFoundError):
        run([tmp_path / "nothing.exe"])


def test_timeout_stops_the_program() -> None:
    started = time.monotonic()
    with pytest.raises(ProcessTimeoutError):
        run(python("import time; time.sleep(30)"), timeout=0.5)
    assert time.monotonic() - started < 10


def test_cancel_stops_the_program() -> None:
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(ProcessCancelledError):
        run(python("import time; time.sleep(30)"), cancel=cancel)
    assert time.monotonic() - started < 10


def test_stdin_is_closed() -> None:
    result = run(python("import sys; print(repr(sys.stdin.read()))"), timeout=10)
    assert result.stdout.strip() == "''"
