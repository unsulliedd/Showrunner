"""Walking dropped folders and files."""

from __future__ import annotations

import stat
from collections.abc import Iterable, Iterator
from pathlib import Path


def is_hidden(path: Path) -> bool:
    """A dot name, or on Windows a file with the hidden attribute. The app's own work folders are dot folders."""
    if path.name.startswith("."):
        return True
    try:
        # Only Windows has file attributes.
        return bool(getattr(path.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_HIDDEN)
    except OSError:
        return False


def walk_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Every file below the folders, and the files themselves, each once and in name order.

    A dropped folder is entered even if hidden; the hidden ones inside it are not.
    """
    seen: set[Path] = set()
    for root in roots:
        candidates = [root] if root.is_file() else _files_below(root)
        for path in candidates:
            if path not in seen:
                seen.add(path)
                yield path


def _files_below(root: Path) -> Iterator[Path]:
    for folder, subfolders, names in root.walk():
        # Editing the list in place stops the walk from entering the removed folders.
        subfolders[:] = sorted(n for n in subfolders if not is_hidden(folder / n))
        for name in sorted(names):
            if not is_hidden(folder / name):
                yield folder / name
