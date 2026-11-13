from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from showrunner.app.options.registry import OptionsRegistry
from showrunner.app.options.serialization import LoadWarning, WarningKind, from_sparse, to_sparse


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


@dataclass(frozen=True)
class _NoEnabled:
    count: int = 1


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


@pytest.mark.parametrize("cls", [_NoEnabled, _NotFrozen, _NoDefault, _BadType])
def test_registry_rejects_invalid_declarations(registry: OptionsRegistry, cls: type) -> None:
    with pytest.raises(TypeError):
        registry.register("bad")(cls)
