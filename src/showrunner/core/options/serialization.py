"""Conversion between frozen option dataclasses and sparse, forgiving JSON values.

Supported field types: bool, int, float, str, enums, lists of those, dicts from str to those, and frozen
dataclasses of those (written in full, not sparse). A dataclass converted here needs a default for every
field.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import MISSING, Field, dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Any, cast, get_args, get_origin, get_type_hints


class WarningKind(StrEnum):
    UNKNOWN_STAGE = "unknown-stage"
    UNKNOWN_KEY = "unknown-key"
    WRONG_TYPE = "wrong-type"
    NEWER_FORMAT = "newer-format"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class LoadWarning:
    """A problem met while loading a file. `location` is a dotted path such as `tracks.keep`."""

    kind: WarningKind
    location: str


@dataclass(frozen=True, slots=True)
class Loaded[T]:
    value: T
    warnings: list[LoadWarning] = field(default_factory=list)


class _MismatchError(Exception):
    """A JSON value does not fit the declared field type."""


def _decode(tp: Any, raw: Any) -> Any:
    origin = get_origin(tp)
    if origin is list:
        if not isinstance(raw, list):
            raise _MismatchError
        (item_type,) = get_args(tp)
        return [_decode(item_type, item) for item in raw]
    if origin is dict:
        if not isinstance(raw, dict):
            raise _MismatchError
        _, value_type = get_args(tp)
        return {key: _decode(value_type, value) for key, value in raw.items()}
    if isinstance(tp, type) and is_dataclass(tp):
        if not isinstance(raw, dict):
            raise _MismatchError
        hints = get_type_hints(tp)
        if not raw.keys() <= hints.keys():
            raise _MismatchError
        return tp(**{key: _decode(hints[key], value) for key, value in raw.items()})
    # bool is a subclass of int in Python, so each check has to rule it in or out explicitly.
    if tp is bool:
        if isinstance(raw, bool):
            return raw
    elif tp is int:
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
    elif tp is float:
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return float(raw)
    elif tp is str:
        if isinstance(raw, str):
            return raw
    elif isinstance(tp, type) and issubclass(tp, Enum):
        try:
            return tp(raw)
        except (ValueError, TypeError):
            pass
    raise _MismatchError


def _encode(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _default(f: Field[Any]) -> Any:
    if f.default_factory is not MISSING:
        return f.default_factory()
    return f.default


def _check_type(tp: Any) -> None:
    if tp in (bool, int, float, str) or (isinstance(tp, type) and issubclass(tp, Enum)):
        return
    if get_origin(tp) is list:
        (item_type,) = get_args(tp)
        _check_type(item_type)
        return
    if get_origin(tp) is dict:
        key_type, value_type = get_args(tp)
        # JSON object keys are always strings.
        if key_type is not str:
            raise TypeError(f"unsupported option type: {tp!r}")
        _check_type(value_type)
        return
    if isinstance(tp, type) and is_dataclass(tp):
        validate_declaration(tp)
        return
    raise TypeError(f"unsupported option type: {tp!r}")


def validate_declaration(cls: type) -> None:
    """Raise TypeError unless `cls` is a frozen dataclass of supported, defaulted fields."""
    # The type stubs do not declare __dataclass_params__, which the dataclass decorator sets at runtime.
    if not is_dataclass(cls) or not cast(Any, cls).__dataclass_params__.frozen:
        raise TypeError(f"{cls.__name__} must be a frozen dataclass")
    hints = get_type_hints(cls)
    for f in fields(cls):
        if f.default is MISSING and f.default_factory is MISSING:
            raise TypeError(f"{cls.__name__}.{f.name} has no default")
        _check_type(hints[f.name])


def to_sparse(obj: Any) -> dict[str, Any]:
    """Only the fields that differ from their defaults, in JSON-ready form."""
    return {f.name: _encode(getattr(obj, f.name)) for f in fields(obj) if getattr(obj, f.name) != _default(f)}


def to_fields(obj: Any, names: Iterable[str]) -> dict[str, Any]:
    """The named fields in JSON-ready form, also those equal to their defaults."""
    return {name: _encode(getattr(obj, name)) for name in names}


def from_sparse(cls: type, data: Any, where: str, warnings: list[LoadWarning]) -> Any:
    """Build `cls` from sparse JSON. Bad or unknown entries are skipped and reported in `warnings`."""
    return cls(**from_fields(cls, data, where, warnings))


def from_fields(cls: type, data: Any, where: str, warnings: list[LoadWarning]) -> dict[str, Any]:
    """The fields of `cls` that JSON `data` holds, decoded; bad or unknown entries are skipped and reported."""
    if not isinstance(data, dict):
        warnings.append(LoadWarning(WarningKind.WRONG_TYPE, where))
        return {}
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    values: dict[str, Any] = {}
    for key, raw in data.items():
        location = f"{where}.{key}"
        if key not in known:
            warnings.append(LoadWarning(WarningKind.UNKNOWN_KEY, location))
            continue
        try:
            values[key] = _decode(hints[key], raw)
        except _MismatchError:
            warnings.append(LoadWarning(WarningKind.WRONG_TYPE, location))
    return values
