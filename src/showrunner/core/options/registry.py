"""The registry that maps a stage id to the options class that stage declares."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from showrunner.core.options.serialization import validate_declaration


class OptionsRegistry:
    def __init__(self) -> None:
        self._classes: dict[str, type] = {}

    def register[T: type](self, stage_id: str) -> Callable[[T], T]:
        """Class decorator: `@REGISTRY.register("tracks")` on a frozen options dataclass."""

        def decorator(cls: T) -> T:
            if stage_id in self._classes:
                raise ValueError(f"stage {stage_id!r} is already registered")
            validate_declaration(cls)
            self._classes[stage_id] = cls
            return cls

        return decorator

    def get(self, stage_id: str) -> type:
        return self._classes[stage_id]

    def ids(self) -> list[str]:
        return list(self._classes)

    def defaults(self) -> dict[str, Any]:
        return {stage_id: cls() for stage_id, cls in self._classes.items()}


# Stages register here when their module is imported.
REGISTRY = OptionsRegistry()
