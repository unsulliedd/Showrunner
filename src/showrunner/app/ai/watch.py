"""Whether the AI server answers and which models it has, as last checked.

Plans are made on the window's thread and must never wait for a server, so they read the last answer (`status`), and
the window asks again in the background (`check`) once that answer is older than `FRESH_SECONDS`. An old answer stays
in use until a newer one arrives: the plan a user reviewed is not changed under them by an answer simply growing old.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from showrunner.stages.subtitles import AiModels
from showrunner.tools.ai import AiError, Backend

FRESH_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class AiStatus:
    backend: str  # the backend's id: its name in the strings and its dependency entry
    running: bool
    models: tuple[str, ...] = ()  # installed, sorted; empty while the server does not answer
    # Why the server did not answer, for the log; not part of the state, so another wording of the same error is no
    # change.
    detail: str = field(default="", compare=False)


class AiWatch:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self._lock = threading.Lock()
        self._status: AiStatus | None = None
        self._checked = 0.0

    def status(self) -> AiStatus | None:
        """The last answer, however old; None before the first check has ended."""
        with self._lock:
            return self._status

    def stale(self) -> bool:
        with self._lock:
            return self._status is None or time.monotonic() - self._checked > FRESH_SECONDS

    def check(self) -> AiStatus:
        """Ask the server now; takes at most a second or so when it is stopped. Call it off the window's thread."""
        try:
            status = AiStatus(self.backend.name, True, tuple(self.backend.models()))
        except AiError as error:
            status = AiStatus(self.backend.name, False, detail=str(error))
        with self._lock:
            self._status, self._checked = status, time.monotonic()
        return status


def ai_models(status: AiStatus | None, default: str) -> AiModels | None:
    """What the plans may use: the model chosen in Settings and the installed ones, or None while no server answers,
    which makes AI work unavailable."""
    if status is None or not status.running:
        return None
    return AiModels(default, status.models)
