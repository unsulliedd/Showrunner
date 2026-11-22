"""The program the ffsubsync adapter starts: ffsubsync run in a child process, answering in plain lines.

ffsubsync's library cannot be cancelled (it runs ffmpeg and a long computation inside the caller), and its answer
leaves out the score. In a child process of its own Cancel kills the process, the heavy imports never load into the
app, and the worker can read the score from ffsubsync's log. Standard output holds only these lines:

    progress <fraction>
    result {"offset": ..., "scale": ..., "score": ..., "ok": true}
    error <message>
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Sequence

_SCORE = re.compile(r"^score: (-?[\d.]+)")
_STEP = 0.01  # progress is written when it moved by this much


class _Collector(logging.Handler):
    """Keeps the score ffsubsync logs and the errors it logs instead of raising."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.score: float | None = None
        self.errors: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if found := _SCORE.match(message):
            self.score = float(found[1])
        elif record.levelno >= logging.ERROR:
            cause = record.exc_info[1] if record.exc_info else None
            self.errors.append(f"{message}: {cause}" if cause else message)


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str]) -> int:
    from ffsubsync.ffsubsync import logger, make_parser, run

    collector = _Collector()
    logger.addHandler(collector)
    logger.setLevel(min(logger.getEffectiveLevel(), logging.INFO))  # the score is logged at this level
    reported = [-1.0]

    def progress(info: object) -> None:
        total = getattr(info, "total_seconds", None)
        if total:
            fraction = min(getattr(info, "processed_seconds", 0.0) / total, 1.0)
            if fraction - reported[0] >= _STEP:
                reported[0] = fraction
                _say(f"progress {fraction:.3f}")

    try:
        outcome = run(make_parser().parse_args(list(argv)), progress_handler=progress)
    except SystemExit:
        _say("error the arguments were refused")
        return 2
    except Exception as error:  # ffsubsync reports its own failures through the log; this is the rest
        _say(f"error {error}")
        return 2
    offset = outcome.get("offset_seconds")
    if offset is None or collector.score is None:
        _say("error " + ("; ".join(collector.errors) or "ffsubsync found no alignment"))
        return 2
    _say(
        "result "
        + json.dumps(
            {
                "offset": offset,
                "scale": outcome.get("framerate_scale_factor") or 1.0,
                "score": collector.score,
                "ok": bool(outcome.get("sync_was_successful")),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
