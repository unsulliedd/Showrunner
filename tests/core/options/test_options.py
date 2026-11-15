from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from showrunner.core.options.registry import OptionsRegistry
from showrunner.core.options.serialization import LoadWarning, WarningKind, from_sparse, to_sparse


def test_defaults_serialize_to_nothing(example: Any) -> None:
    assert to_sparse(example()) == {}


def test_only_changed_values_are_written(example: Any, mode: Any) -> None:
    options = example(count=5, mode=mode.SLOW, names=["a", "b", "c"])
    assert to_sparse(options) == {"count": 5, "mode": "slow", "names": ["a", "b", "c"]}


def test_round_trip(example: Any, mode: Any) -> None:
    options = example(False, True, 9, 1.5, "y", mode.SLOW, ["z"], [mode.SLOW, mode.FAST])
    warnings: list[LoadWarning] = []
    assert from_sparse(example, to_sparse(options), "example", warnings) == options
    assert warnings == []


def test_wrong_types_fall_back_to_defaults_with_warnings(example: Any) -> None:
    data = {
        "enabled": "yes",
        "count": True,  # a bool is not an int
        "ratio": "high",
        "mode": "warp",
        "names": ["a", 1],
        "modes": "fast",
        "flag": True,
    }
    warnings: list[LoadWarning] = []
    assert from_sparse(example, data, "example", warnings) == example(flag=True)
    assert {w.location for w in warnings} == {f"example.{key}" for key in data if key != "flag"}
    assert {w.kind for w in warnings} == {WarningKind.WRONG_TYPE}


def test_int_is_accepted_for_float(example: Any) -> None:
    assert from_sparse(example, {"ratio": 2}, "example", []).ratio == 2.0


def test_unknown_key_is_reported_and_ignored(example: Any) -> None:
    warnings: list[LoadWarning] = []
    assert from_sparse(example, {"gone": 1}, "example", warnings) == example()
    assert warnings == [LoadWarning(WarningKind.UNKNOWN_KEY, "example.gone")]


def test_registry_lists_stage_ids_and_defaults(registry: OptionsRegistry, example: Any) -> None:
    assert registry.ids() == ["example"]
    assert registry.get("example") is example
    assert registry.defaults() == {"example": example()}


def test_registry_rejects_duplicate_stage_id(registry: OptionsRegistry, example: Any) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register("example")(example)


@dataclass
class _NotFrozen:
    enabled: bool = True


@dataclass(frozen=True)
class _NoDefault:
    enabled: bool


@dataclass(frozen=True)
class _BadType:
    enabled: bool = True
    value: dict[str, int] | None = None


@pytest.mark.parametrize("cls", [_NotFrozen, _NoDefault, _BadType])
def test_registry_rejects_invalid_declarations(registry: OptionsRegistry, cls: type) -> None:
    with pytest.raises(TypeError):
        registry.register("bad")(cls)


@dataclass(frozen=True)
class _WithDict:
    enabled: bool = True
    paths: dict[str, str] = field(default_factory=dict)
    modes: dict[str, list[int]] = field(default_factory=dict)


def test_dicts_round_trip_and_bad_values_are_reported() -> None:
    value = _WithDict(paths={"a": "x"}, modes={"b": [1, 2]})
    data = to_sparse(value)
    assert data == {"paths": {"a": "x"}, "modes": {"b": [1, 2]}}
    warnings: list[LoadWarning] = []
    assert from_sparse(_WithDict, data, "w", warnings) == value
    assert warnings == []
    assert from_sparse(_WithDict, {"paths": {"a": 1}, "modes": [1]}, "w", warnings) == _WithDict()
    assert warnings == [LoadWarning(WarningKind.WRONG_TYPE, "w.paths"), LoadWarning(WarningKind.WRONG_TYPE, "w.modes")]


@dataclass(frozen=True)
class _IntKeys:
    enabled: bool = True
    value: dict[int, str] = field(default_factory=dict)


def test_dict_keys_must_be_strings(registry: OptionsRegistry) -> None:
    registry.register("with_dict")(_WithDict)
    with pytest.raises(TypeError):
        registry.register("int_keys")(_IntKeys)


@dataclass(frozen=True)
class Entry:
    name: str = ""
    mode: str = "a"


@dataclass(frozen=True)
class WithEntries:
    enabled: bool = True
    entries: list[Entry] = field(default_factory=list)


def test_nested_dataclasses_round_trip_in_full() -> None:
    options = WithEntries(entries=[Entry("x", "b"), Entry("y")])
    sparse = to_sparse(options)
    assert sparse == {"entries": [{"name": "x", "mode": "b"}, {"name": "y", "mode": "a"}]}
    warnings: list[LoadWarning] = []
    assert from_sparse(WithEntries, sparse, "w", warnings) == options
    assert warnings == []


def test_nested_dataclass_with_bad_data_is_rejected_with_a_warning() -> None:
    for bad in ([{"name": "x", "gone": 1}], [{"name": 3}], ["x"], "x"):
        warnings: list[LoadWarning] = []
        assert from_sparse(WithEntries, {"entries": bad}, "w", warnings) == WithEntries()
        assert warnings == [LoadWarning(WarningKind.WRONG_TYPE, "w.entries")]


def test_nested_dataclass_missing_a_key_takes_its_default() -> None:
    assert from_sparse(WithEntries, {"entries": [{"name": "x"}]}, "w", []).entries == [Entry("x")]


@dataclass(frozen=True)
class NoDefault:
    name: str


@dataclass(frozen=True)
class Holder:
    enabled: bool = True
    entries: list[NoDefault] = field(default_factory=list)


def test_registry_rejects_a_nested_dataclass_without_defaults() -> None:
    with pytest.raises(TypeError):
        OptionsRegistry().register("holder")(Holder)
