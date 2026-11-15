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


def test_on_line_gets_each_line_while_the_program_runs() -> None:
    seen: list[tuple[str, float]] = []
    code = (
        "import sys, time\n"
        "for n in range(3):\n    print(f'step {n}', flush=True)\n    time.sleep(0.2)\n"
        "print('e', file=sys.stderr)"
    )
    result = run(python(code), on_line=lambda line: seen.append((line, time.monotonic())))
    assert [line for line, _ in seen] == ["step 0", "step 1", "step 2"]
    assert seen[-1][1] - seen[0][1] > 0.2  # delivered as written, not all at the end
    assert result.stdout == "step 0\nstep 1\nstep 2"
    assert result.stderr.strip() == "e"


def test_cancel_stops_a_streaming_program() -> None:
    cancel = threading.Event()
    lines: list[str] = []

    def on_line(line: str) -> None:
        lines.append(line)
        cancel.set()

    started = time.monotonic()
    with pytest.raises(ProcessCancelledError):
        run(python("import time\nprint('go', flush=True)\ntime.sleep(30)"), cancel=cancel, on_line=on_line)
    assert lines == ["go"]
    assert time.monotonic() - started < 10
