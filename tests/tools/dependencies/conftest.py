from __future__ import annotations

from collections.abc import Callable

import pytest

from showrunner.tools.dependencies.specs import Archive, DependencySpec, Feature, GitHubRelease, Variant


def make_spec(
    executables: tuple[str, ...] = ("tool",),
    *,
    version_args: tuple[str, ...] | None = ("--version",),
    min_version: str | None = "2.0",
    install_dirs: tuple[str, ...] = (),
    variants: tuple[Variant, ...] = (Variant("default", (r"tool-[\d.]+-win\.zip",), Archive.ZIP),),
    prerelease: bool = False,
    features: tuple[Feature, ...] = (Feature.MUX,),
    spec_id: str = "tool",
) -> DependencySpec:
    return DependencySpec(
        id=spec_id,
        executables=executables,
        version_args=version_args,
        version_pattern=r"tool v(\d+(?:\.\d+)+)",
        min_version=min_version,
        official_url="https://example.org/tool",
        source=GitHubRelease("owner/tool", variants, prerelease),
        features=features,
        install_dirs=install_dirs,
    )


@pytest.fixture
def spec_factory() -> Callable[..., DependencySpec]:
    """Test modules cannot import from a conftest under importlib mode, so the builder is a fixture."""
    return make_spec


@pytest.fixture
def spec() -> DependencySpec:
    return make_spec()
