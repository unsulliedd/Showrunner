"""Moving files to the Windows Recycle Bin, through the shell's own file operation and never as a delete."""

from __future__ import annotations

import contextlib
import ctypes
import os
from collections.abc import Sequence
from pathlib import Path

_FO_DELETE = 3
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
# Where the shell cannot recycle a file it would delete it for good; this flag makes it ask the user first, the
# last guard behind the checks below.
_FOF_WANTNUKEWARNING = 0x4000
_FLAGS = _FOF_SILENT | _FOF_NOCONFIRMATION | _FOF_ALLOWUNDO | _FOF_NOERRORUI | _FOF_WANTNUKEWARNING
# Only fixed drives keep a Recycle Bin; network shares and most removable drives delete at once.
_DRIVE_FIXED = 3
_BIT_BUCKET = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"
_MEGABYTE = 1024 * 1024


class RecycleError(OSError):
    """The files cannot go to the Recycle Bin; nothing was deleted."""


class _FileOperation(ctypes.Structure):
    """SHFILEOPSTRUCTW."""

    _fields_ = (
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    )


def recycle(paths: Sequence[Path]) -> None:
    """Move the files to the Recycle Bin in one shell operation. Raises `RecycleError` before anything is moved
    when a file's drive has no Recycle Bin, the bin is set to delete at once, or a file is larger than the bin
    holds; also when the operation is aborted or a file is still in place afterwards."""
    if not paths:
        return
    if os.name != "nt":
        raise RecycleError("the Recycle Bin is available on Windows only")
    full = [path.resolve() for path in paths]
    for path in full:
        _check(path)
    operation = _FileOperation()
    operation.wFunc = _FO_DELETE
    # A list of paths, each ended by a null character, with one more null character at the end.
    # A buffer, not a plain string: a string argument would end at the first null character.
    names = ctypes.create_unicode_buffer("".join(f"{path}\0" for path in full) + "\0")
    operation.pFrom = ctypes.cast(names, ctypes.c_wchar_p)
    operation.fFlags = _FLAGS
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))  # type: ignore[attr-defined]
    if code != 0 or operation.fAnyOperationsAborted:
        raise RecycleError(f"the shell did not move the files to the Recycle Bin (code {code})")
    if left := [path for path in full if path.exists()]:
        raise RecycleError(f"still in place after recycling: {', '.join(p.name for p in left)}")


def _check(path: Path) -> None:
    kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
    root = ctypes.create_unicode_buffer(1024)
    if not kernel.GetVolumePathNameW(str(path), root, len(root)):
        raise RecycleError(f"the drive of {path.name} cannot be read")
    if kernel.GetDriveTypeW(root.value) != _DRIVE_FIXED:
        raise RecycleError(f"{root.value} has no Recycle Bin")
    volume = ctypes.create_unicode_buffer(1024)
    if not kernel.GetVolumeNameForVolumeMountPointW(root.value, volume, len(volume)):
        return  # a folder mounted from elsewhere; the shell's own warning still guards it
    settings = _bin_settings(volume.value)
    if settings.get("NukeOnDelete"):
        raise RecycleError(f"the Recycle Bin of {root.value} is set to delete files at once")
    capacity = settings.get("MaxCapacity")
    if capacity is not None and path.stat().st_size > capacity * _MEGABYTE:
        raise RecycleError(f"{path.name} is larger than the Recycle Bin of {root.value} holds")


def _bin_settings(volume: str) -> dict[str, int]:
    """The per-volume settings of the Recycle Bin; empty when the user never changed them."""
    import winreg

    guid = volume[volume.find("{") : volume.find("}") + 1]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{_BIT_BUCKET}\{guid}") as key:
            values = {}
            for name in ("NukeOnDelete", "MaxCapacity"):
                with contextlib.suppress(OSError):
                    values[name] = int(winreg.QueryValueEx(key, name)[0])
            return values
    except OSError:
        return {}
