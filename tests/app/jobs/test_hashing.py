from __future__ import annotations

import os
from pathlib import Path

import pytest

from showrunner.app.jobs.hashing import BLOCK_SIZE, stamp


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_a_moved_copy_has_the_same_hash(tmp_path: Path) -> None:
    data = os.urandom(3 * BLOCK_SIZE)
    first = stamp(write(tmp_path / "a" / "Show S01E01.mkv", data))
    moved = stamp(write(tmp_path / "b" / "renamed.mkv", data))
    assert moved.content_hash == first.content_hash
    assert moved.size == first.size == 3 * BLOCK_SIZE


@pytest.mark.parametrize("offset", [0, 3 * BLOCK_SIZE - 1])
def test_a_change_in_the_first_or_last_block_changes_the_hash(tmp_path: Path, offset: int) -> None:
    data = bytearray(os.urandom(3 * BLOCK_SIZE))
    before = stamp(write(tmp_path / "a.mkv", bytes(data))).content_hash
    data[offset] ^= 0xFF
    assert stamp(write(tmp_path / "a.mkv", bytes(data))).content_hash != before


def test_a_change_in_the_middle_is_not_seen(tmp_path: Path) -> None:
    data = bytearray(os.urandom(3 * BLOCK_SIZE))
    before = stamp(write(tmp_path / "a.mkv", bytes(data))).content_hash
    data[BLOCK_SIZE + 10] ^= 0xFF
    assert stamp(write(tmp_path / "a.mkv", bytes(data))).content_hash == before


def test_the_size_is_part_of_the_hash(tmp_path: Path) -> None:
    assert stamp(write(tmp_path / "a", b"")).content_hash != stamp(write(tmp_path / "b", b"\0")).content_hash


def test_a_short_file_is_hashed_whole(tmp_path: Path) -> None:
    data = os.urandom(BLOCK_SIZE + 100)
    before = stamp(write(tmp_path / "a", data)).content_hash
    changed = data[: BLOCK_SIZE + 50] + bytes([data[BLOCK_SIZE + 50] ^ 0xFF]) + data[BLOCK_SIZE + 51 :]
    assert stamp(write(tmp_path / "a", changed)).content_hash != before


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        stamp(tmp_path / "missing.mkv")
