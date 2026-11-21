"""About: its link buttons open the project's pages, and only those."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from showrunner.ui.quick.settings import LINKS, REPOSITORY
from showrunner.ui.quick.window import WindowController


@pytest.fixture
def opened_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url.toString()) or True)
    return urls


def test_a_link_button_opens_its_page(controller: WindowController, opened_urls: list[str]) -> None:
    links = controller.settings.links
    assert [link["key"] for link in links] == ["release_notes", "source", "report"]
    assert all(link["label"] for link in links)
    for link in links:
        controller.settings.open_link(link["url"])
    assert opened_urls == [REPOSITORY + "/releases", REPOSITORY, REPOSITORY + "/issues"]


def test_an_address_that_is_not_a_link_of_the_page_is_not_opened(
    controller: WindowController, opened_urls: list[str]
) -> None:
    controller.settings.open_link("https://example.com/")
    controller.settings.open_link(QUrl.fromLocalFile("C:/Windows").toString())
    assert opened_urls == []


def test_the_project_urls_of_the_package_are_the_pages_about_links_to() -> None:
    pyproject = Path(__file__).parents[3] / "pyproject.toml"
    urls = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["urls"]
    assert urls == {"Homepage": REPOSITORY, "Source": REPOSITORY, "Issues": LINKS["report"]}
