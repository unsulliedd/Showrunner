from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.app.profiles.store import ProfileStore
from showrunner.app.settings.app_settings import Startup, load_settings
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.core.track import AudioProperties, Track, TrackKind, VideoProperties
from showrunner.stages.tracks import KindTest, TrackMatch, TrackRule, Verdict
from showrunner.ui.settings.general import Workspace
from showrunner.ui.settings.programs import ProgramsPage
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.settings.window import SettingsWindow
from showrunner.ui.theme.manager import ThemeManager

ITEM = MediaItem(
    Episode("Show Name", 1, 5, 2020, "Episode Five"),
    MediaFile(
        Path("Show Name S01E05.mkv"),
        "matroska",
        tracks=(
            Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
            Track(1, TrackKind.AUDIO, "A_EAC3", Language("eng"), audio=AudioProperties(6)),
            Track(2, TrackKind.AUDIO, "A_AC3", Language("eng"), "Commentary", audio=AudioProperties(2)),
        ),
    ),
)


@pytest.fixture(autouse=True)
def no_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Programs page checks the programs as it opens; tests must not run the machine's own.
    monkeypatch.setattr(ProgramsPage, "check_all", lambda self: None)


@pytest.fixture
def session(qapp: QApplication, tmp_path: Path) -> ProfileSession:
    return ProfileSession(ProfileStore(tmp_path / "profiles"))


@pytest.fixture
def window(theme: ThemeManager, session: ProfileSession) -> SettingsWindow:
    window = SettingsWindow(theme, session, lambda: Workspace(("Show Name",), "Show Name S01E05", 288, 320))
    window.show()
    return window


def test_every_page_opens_with_every_string_found(
    theme: ThemeManager, session: ProfileSession, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="showrunner.ui.i18n"):
        window = SettingsWindow(theme, session, Workspace)
        window.show()
        for page in ("general", "profiles", "naming", "tracks", "programs", "appearance"):
            window.open_page(page)
            assert window.current_page() == page
        window.set_item(ITEM)
        QApplication.processEvents()
    assert caplog.records == []
    assert not window.isModal()
    window.close()


def test_startup_is_saved_at_once(window: SettingsWindow) -> None:
    window.general.buttons[Startup.EMPTY].setChecked(True)
    assert load_settings().value.startup is Startup.EMPTY


def test_an_unknown_token_is_underlined_and_offers_the_fix(window: SettingsWindow, session: ProfileSession) -> None:
    editor = window.naming.editors["audio_track_template"]
    editor.field.setPlainText("{language} {chanels}")
    editor.field.flush()
    assert session.options("naming").audio_track_template == "{language} {chanels}"
    assert editor.shown == ["Unknown token {chanels}. Did you mean {channels}?"]
    assert editor.field.property("problem") is True
    assert "metadata" in session.blocks()
    assert window.naming.footer.status.text().startswith("1 problem in Naming")
    editor.field.replace_range(11, 20, "{channels}")
    assert session.options("naming").audio_track_template == "{language} {channels}"
    assert editor.shown == []


def test_the_previews_follow_the_selected_file(window: SettingsWindow) -> None:
    window.set_item(ITEM)
    lines = window.naming.previews["audio_track_template"]
    texts = [lines.itemAt(i).layout().itemAt(1).widget().text() for i in range(lines.count())]
    assert texts == ["Show Name S01E05 (Dolby Digital Plus 5.1)", "Show Name S01E05 (Dolby Digital 2.0 Commentary)"]


def test_default_is_saved_as_a_new_profile(window: SettingsWindow, session: ProfileSession) -> None:
    footer = window.naming.footer
    session.update("naming", title_template="{show}")
    assert not footer.save.isEnabled()
    assert footer.status.text() == "Default is built in. Save your changes as a new profile."
    footer.ask_name = lambda: "Mine"  # type: ignore[method-assign]
    footer.save_as.click()
    assert (session.name, session.is_changed) == ("Mine", False)
    assert load_settings().value.active_profile == "Mine"


def test_a_broken_rule_is_marked_and_explained(window: SettingsWindow, session: ProfileSession) -> None:
    window.set_item(ITEM)
    rule = TrackRule(label="Keep English", match=TrackMatch(kind=KindTest.AUDIO, languages=["egn"]))
    session.update("tracks", enabled=True, rules=[rule])
    page = window.tracks
    page.select_rule(0)
    assert page.languages.shown == ["Not a language code: egn. Did you mean eng?"]
    assert page.has_problem()
    assert not window.nav.item(4).icon().isNull()
    assert not page.strip.isHidden()
    page.languages.field.replace_range(0, 3, "eng")
    assert session.options("tracks").rules[0].match.languages == ["eng"]
    assert not page.has_problem()


def test_the_result_shows_a_refusal(window: SettingsWindow, session: ProfileSession) -> None:
    window.set_item(ITEM)
    drop = TrackRule(label="Drop audio", match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.DROP)
    session.update("tracks", enabled=True, rules=[drop])
    page = window.tracks
    assert page.strip.text().startswith("No plan for this file: the rules would leave no audio track")
    outcomes = [page.result_model.item(row, 4).text() for row in range(page.result_model.rowCount())]
    assert outcomes == ["—", "Would be dropped by rule 1 Drop audio", "Would be dropped by rule 1 Drop audio"]


def test_rules_are_added_moved_and_deleted(window: SettingsWindow, session: ProfileSession) -> None:
    page = window.tracks
    page._add()
    page._add()
    page.label_field.setText("Second")
    page.label_field.editingFinished.emit()
    page._move(-1)
    assert [r.label for r in session.options("tracks").rules] == ["Second", "New rule"]
    page._delete()
    assert [r.label for r in session.options("tracks").rules] == ["New rule"]


def test_profiles_duplicate_and_switch(window: SettingsWindow, session: ProfileSession) -> None:
    page = window.profiles
    page.ask_text = lambda title, text, value="": "TV"  # type: ignore[method-assign]
    page._duplicate()
    assert session.store.names() == ["Default", "TV"]
    assert page.selected() == "TV"
    page.use.click()
    assert session.name == "TV"
    assert window.nav.item(2).text() == "In profile TV"


def test_typing_a_list_keeps_the_text_as_typed(window: SettingsWindow, session: ProfileSession) -> None:
    session.update("tracks", enabled=True, rules=[TrackRule()])
    page = window.tracks
    page.select_rule(0)
    page.languages.field.setPlainText("tur,eng")
    page.languages.field.flush()
    assert session.options("tracks").rules[0].match.languages == ["tur", "eng"]
    assert page.languages.field.text() == "tur,eng"
