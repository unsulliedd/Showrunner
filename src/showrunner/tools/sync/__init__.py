"""Sync engines: each moves a subtitle onto the timing of a reference behind one interface (`SyncAdapter`)."""

from showrunner.tools.sync.base import (
    IN_SYNC_BELOW,
    UNSURE_BELOW,
    Setting,
    SettingKind,
    SyncAdapter,
    SyncError,
    SyncOutcome,
    SyncRequest,
)
from showrunner.tools.sync.ffsubsync import FfsubsyncAdapter

# The engines this version has, by the name their options use.
ENGINES = {FfsubsyncAdapter.name: FfsubsyncAdapter}

__all__ = [
    "ENGINES",
    "IN_SYNC_BELOW",
    "UNSURE_BELOW",
    "FfsubsyncAdapter",
    "Setting",
    "SettingKind",
    "SyncAdapter",
    "SyncError",
    "SyncOutcome",
    "SyncRequest",
]
