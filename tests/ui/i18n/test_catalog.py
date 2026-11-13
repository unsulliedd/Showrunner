from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from showrunner.ui.i18n.catalog import STRINGS_DIR, StringCatalog


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "en.json").write_text(
        json.dumps({"greeting": "Hello", "only_en": "English", "count": "{n} files"}), encoding="utf-8"
    )
    (tmp_path / "de.json").write_text(json.dumps({"greeting": "Hallo", "count": "{n} Dateien"}), encoding="utf-8")
    return tmp_path


def test_active_language_first(folder: Path) -> None:
    assert StringCatalog(folder, "de").text("greeting") == "Hallo"


def test_missing_key_falls_back_to_english_then_to_the_key(folder: Path) -> None:
    catalog = StringCatalog(folder, "de")
    assert catalog.text("only_en") == "English"
    assert catalog.text("nowhere") == "nowhere"


def test_missing_key_is_reported_once(folder: Path, caplog: pytest.LogCaptureFixture) -> None:
    catalog = StringCatalog(folder, "de")
    with caplog.at_level(logging.WARNING):
        catalog.text("only_en")
        catalog.text("only_en")
    assert len([r for r in caplog.records if "only_en" in r.getMessage()]) == 1


def test_placeholders_are_filled(folder: Path) -> None:
    assert StringCatalog(folder, "de").text("count", n=3) == "3 Dateien"
    # A wrong placeholder in a catalog shows the raw template instead of failing.
    assert StringCatalog(folder).text("count") == "{n} files"


def test_unknown_language_uses_english(folder: Path) -> None:
    catalog = StringCatalog(folder, "xx")
    assert catalog.language == "en"
    assert catalog.text("greeting") == "Hello"


def test_every_literal_key_in_the_ui_is_in_the_english_catalog() -> None:
    english = json.loads((STRINGS_DIR / "en.json").read_text(encoding="utf-8"))
    ui_dir = STRINGS_DIR.parent.parent
    used = {key for path in ui_dir.rglob("*.py") for key in re.findall(r'\btr\("([^"]+)"', path.read_text("utf-8"))}
    assert used
    assert sorted(used - english.keys()) == []
