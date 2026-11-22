"""Atomic file writing."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` as UTF-8 so that `path` holds either the old content or the new, never a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temporary file sits in the target folder: a replace across volumes is not atomic.
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_name)
        raise


def write_json_atomic(path: Path, data: Any) -> None:
    """Write `data` as JSON with the guarantee of `write_text_atomic`."""
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
