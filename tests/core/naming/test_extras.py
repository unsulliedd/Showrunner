from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.core.media import Extra, MediaFile, MediaItem
from showrunner.core.naming import NamingContext, preview

ITEM = MediaItem(Extra("Show Name", "Behind the Scenes", 2020), MediaFile(Path("Behind the Scenes.mkv"), "matroska"))


def render(template: str) -> str:
    return preview(template, NamingContext(ITEM)).text


@pytest.mark.parametrize("template", ["{season}", "{episode}", "{episode_code}", "{movie}", "{season:00}"])
def test_an_extra_has_no_value_for_the_episode_and_movie_tokens(template: str) -> None:
    assert render(f"x{template}") == "x"


def test_a_group_around_an_empty_episode_token_is_left_out() -> None:
    assert render("{show}[ - {episode_code}]") == "Show Name"
    assert render("{file_name}") == "Behind the Scenes"


def test_an_extra_reads_the_show_its_title_and_the_year_of_the_show() -> None:
    assert render("{show} ({year}) - {episode_title}") == "Show Name (2020) - Behind the Scenes"
    assert render("{title}") == "Show Name"
