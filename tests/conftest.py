import os
from dataclasses import dataclass, field
from enum import StrEnum

# Must be set before Qt loads a platform plugin: renders to memory, so tests need no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.core.options.registry import OptionsRegistry


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    # Qt allows one QApplication per process, so it is shared by every test.
    return QApplication.instance() or QApplication([])


class Mode(StrEnum):
    FAST = "fast"
    SLOW = "slow"


# Stands in for a real stage: one field of each supported kind.
@dataclass(frozen=True)
class ExampleOptions:
    enabled: bool = True
    flag: bool = False
    count: int = 3
    ratio: float = 0.5
    label: str = "x"
    mode: Mode = Mode.FAST
    names: list[str] = field(default_factory=lambda: ["a", "b"])
    modes: list[Mode] = field(default_factory=list)


@pytest.fixture
def registry() -> OptionsRegistry:
    registry = OptionsRegistry()
    registry.register("example")(ExampleOptions)
    return registry


@pytest.fixture
def example() -> type[ExampleOptions]:
    return ExampleOptions


@pytest.fixture
def mode() -> type[Mode]:
    return Mode
