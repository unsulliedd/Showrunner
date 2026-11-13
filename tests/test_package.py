import importlib

import pytest

import showrunner

LAYERS = ["core", "tools", "stages", "app", "ui", "cli"]


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_imports_with_docstring(layer: str) -> None:
    module = importlib.import_module(f"showrunner.{layer}")
    assert module.__doc__


def test_version_is_set() -> None:
    assert showrunner.__version__
