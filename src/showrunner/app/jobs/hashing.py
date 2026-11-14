"""A file's stamp: size, modification time and a fast content hash that survives a rename or a move."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

# One read covers the Matroska header that header edits rewrite; two reads cost nothing next to probing a file.
BLOCK_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class FileStamp:
    size: int
    mtime_ns: int
    # Same for a renamed or moved copy; blind to a change that touches neither end nor the size.
    content_hash: str


def stamp(path: Path) -> FileStamp:
    """Raises OSError when the file cannot be read."""
    with path.open("rb") as handle:
        status = os.fstat(handle.fileno())
        # BLAKE2b is in the standard library and faster than SHA-256 without hardware support; 16 bytes is
        # far more than a library of files needs to tell them apart.
        digest = hashlib.blake2b(status.st_size.to_bytes(8, "little"), digest_size=16)
        digest.update(handle.read(BLOCK_SIZE))
        if status.st_size > BLOCK_SIZE:
            # A file shorter than two blocks has its tail read from the end of the first block, never twice.
            handle.seek(max(status.st_size - BLOCK_SIZE, BLOCK_SIZE))
            digest.update(handle.read(BLOCK_SIZE))
    return FileStamp(status.st_size, status.st_mtime_ns, digest.hexdigest())
