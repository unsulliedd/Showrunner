"""The Settings dialog's Python side: General, Profiles (files, and what each keeps), and the window's controls that
came with it: the command palette, value maps in the Tokens panel, the untagged-track language and deleting a
hand-written rule."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME
from showrunner.app.settings.app_settings import Startup, load_settings
from showrunner.stages.tracks import TrackMatch, TrackRule, Verdict
from showrunner.ui.quick.palette import Entry, search
from showrunner.ui.quick.settings import SECTIONS, SHORTCUT_LIST, SHORTCUTS
from showrunner.ui.quick.window import WindowController

from .test_choices import COMMENTARY, open_season, settle
from .test_names import naming


def test_general_saves_the_startup_at_once(controller: WindowController) -> None:
    settings = controller.settings
    assert [s["key"] for s in settings.sections] == [key for key, _icon in SECTIONS]
    settings.set_startup("empty")
    assert load_settings().value.startup is Startup.EMPTY
    assert settings.startup == "empty"
    settings.set_startup("sometimes")
    assert settings.startup == "empty"
    assert settings.language == "English"


def test_the_shortcuts_list_the_keys_the_window_binds(controller: WindowController) -> None:
    listed = {key for keys, _what in SHORTCUT_LIST for key in keys}
    assert set(SHORTCUTS.values()) <= listed
    assert controller.settings.keys == SHORTCUTS
    assert all(entry["keys"] and entry["text"] for entry in controller.settings.shortcuts)


def test_the_default_profile_cannot_be_changed_or_renamed(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    settings = controller.settings
    assert settings.picked == DEFAULT_PROFILE_NAME
    assert settings.profile["builtin"]
    assert not settings.profile["editable"]
    settings.set_suffix(" [x]")
    assert settings.profile["suffix"] == ""
    assert settings.rename("Mine") != ""
    assert settings.duplicate("Series") == ""
    assert settings.picked == "Series"
    assert settings.profile["editable"]
    assert settings.duplicate("series") == "A profile named series already exists."


def test_a_profile_field_reaches_the_batch_that_follows_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert controller.save_profile_as("Series") == ""
    settings = controller.settings
    settings.open("profiles")
    assert settings.picked == "Series"
    settings.set_original("keep")
    settings.set_keep_folder("  kept ")
    settings.set_suffix(" new")
    settings.set_flags_from_names(False)
    profile = controller.batches.profile(controller.workspace.key)  # type: ignore[arg-type]
    mux = profile.for_stage("mux")
    assert (mux.original, mux.keep_folder, mux.suffix) == ("keep", "kept", " new")
    assert not profile.for_stage("tracks").flags_from_names
    assert controller.store.load("Series").value.for_stage("mux").suffix == " new"
    assert not controller.profile_edited
    settle(controller, qtbot)
    settings.set_keep_folder("a:b")
    assert settings.profile["problems"]["keep_folder"].startswith("“a:b”")


def test_rename_and_delete_carry_the_batch_with_them(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.save_profile_as("Series")
    controller.toggle_keep(COMMENTARY)
    settings = controller.settings
    settings.pick("Series")
    assert settings.rename("Shows") == ""
    assert controller.profile == "Shows"
    assert controller.batches.own(controller.workspace.key)  # type: ignore[arg-type]
    assert [p["name"] for p in settings.profiles] == [DEFAULT_PROFILE_NAME, "Shows"]
    settings.delete()
    assert controller.profile == DEFAULT_PROFILE_NAME
    assert controller.batches.own(controller.workspace.key)  # type: ignore[arg-type]  # the season keeps its choice
    assert settings.picked == DEFAULT_PROFILE_NAME
    assert settings.message == "Shows was deleted."


def test_profiles_wait_while_files_are_applied(
    controller: WindowController, library: Library, qtbot: QtBot, monkeypatch: object
) -> None:
    open_season(controller, library, qtbot)
    controller.save_profile_as("Series")
    controller.run._applying = object()  # type: ignore[assignment]
    settings = controller.settings
    assert settings.profiles_locked
    assert not settings.profile["editable"]
    assert settings.rename("Shows") == "Profiles cannot be changed while files are being applied."
    controller.run._applying = None


def test_a_profile_file_imports_and_exports(
    controller: WindowController, library: Library, qtbot: QtBot, tmp_path: Path
) -> None:
    open_season(controller, library, qtbot)
    controller.save_profile_as("Series")
    settings = controller.settings
    settings.pick("Series")
    settings.export_to(tmp_path / "Shared.json")
    assert settings.message == "Saved as Shared.json."
    settings.import_from(tmp_path / "Shared.json")
    assert settings.picked == "Shared"
    settings.import_from(tmp_path / "Shared.json")
    assert settings.message == "A profile named Shared already exists."
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    settings.import_from(tmp_path / "broken.json")
    assert settings.message == "broken.json is not a profile Showrunner can read."


def test_profiles_change_with_no_batch_selected(controller: WindowController, tmp_path: Path) -> None:
    settings = controller.settings
    assert not controller.has_batch
    assert settings.duplicate("Series") == ""
    settings.set_suffix(" new")
    assert controller.store.load("Series").value.for_stage("mux").suffix == " new"
    settings.export_to(tmp_path / "Shared.json")
    settings.import_from(tmp_path / "Shared.json")
    assert settings.rename("Shows") == ""
    settings.delete()
    assert [p["name"] for p in settings.profiles] == [DEFAULT_PROFILE_NAME, "Series"]
    assert settings.message_tone == "add"
    settings.import_from(tmp_path / "missing.json")
    assert settings.message_tone == "drop"


# The command palette


def test_the_palette_ranks_a_label_that_starts_with_the_query_first() -> None:
    entries = [
        Entry("file", "a", "Another Episode", "Show.S01E01"),
        Entry("action", "b", "Go to Names"),
        Entry("token", "c", "Episode", "{episode}"),
        Entry("action", "d", "Hidden", enabled=False),
    ]
    assert [e.key for e in search("episode", entries)] == ["c", "a"]
    assert [e.key for e in search("s01e01", entries)] == ["a"]
    assert [e.key for e in search("", entries)] == ["b"]
    assert len(search("", [Entry("action", str(i), f"A{i}") for i in range(30)])) == 12


def test_the_palette_ranks_a_word_start_above_a_match_inside_a_word() -> None:
    entries = [
        Entry("file", "inside", "Close Encounters"),
        Entry("file", "word", "Episode Seven"),
        Entry("token", "prefix", "Season", "{season}"),
        Entry("file", "detail", "Pilot", "Show.Base"),
    ]
    assert [e.key for e in search("se", entries)] == ["prefix", "word", "inside", "detail"]
    assert [e.key for e in search("ep se", entries)] == ["word"]


def test_the_palette_finds_files_tracks_tokens_and_actions(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.palette_query = "commentary"
    assert [(r["kind"], r["detail"]) for r in controller.palette] == [("track", "Audio track in this batch")]
    asked: list[tuple[str, str]] = []
    controller.palette_asked.connect(lambda what, key: asked.append((what, key)))
    controller.palette_run("track", "2")
    assert asked == [("place", "tracks")]
    assert controller.palette_query == ""
    controller.palette_run("token", "episode_title")
    assert asked[-1] == ("place", "names")
    assert controller.token_query == "episode_title"
    controller.palette_query = "Movie Title"
    first = controller.palette[0]
    assert first["kind"] == "file"
    controller.palette_run(first["kind"], first["key"])
    assert controller.batch_kind == "movie"
    controller.palette_query = "settings appearance"
    assert [r["key"] for r in controller.palette] == ["settings.appearance"]
    with qtbot.waitSignal(controller.settings.open_asked) as opened:
        controller.palette_run("action", "settings.appearance")
    assert opened.args == ["appearance"]


def test_a_palette_result_that_names_a_place_a_track_or_a_token_leaves_home(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    for kind, key in (("action", "place.tracks"), ("track", "2"), ("token", "episode_title")):
        controller.go_home()
        assert controller.home_shown
        controller.palette_run(kind, key)
        assert not controller.home_shown, key
    controller.go_home()
    controller.palette_run("action", "settings.appearance")
    assert controller.home_shown  # Settings opens over Home


# Value maps, the untagged-track language and deleting a rule


def test_a_value_map_rewrites_a_token_in_the_batch(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.edit_builtin("codec")
    editor = controller.tokens["editor"]
    assert editor["index"] == -1
    assert editor["name"] == "codec"
    assert editor["maps"] == [{"read": "", "written": ""}]
    controller.set_value_map("codec", 0, "HEVC", "x265")
    assert naming(controller).value_maps == {"codec": {"HEVC": "x265"}}
    assert controller.batches.own(controller.workspace.key)  # type: ignore[arg-type]
    editor = controller.tokens["editor"]
    assert editor["maps"][0] == {"read": "HEVC", "written": "x265"}
    controller.set_value_map("codec", 0, "HEVC", "H.265")
    controller.set_value_map("codec", 1, "AVC", "x264")
    assert naming(controller).value_maps == {"codec": {"HEVC": "H.265", "AVC": "x264"}}
    controller.set_value_map("codec", 0, "", "")
    assert naming(controller).value_maps == {"codec": {"AVC": "x264"}}
    controller.set_value_map("codec", 0, "", "")
    assert naming(controller).value_maps == {}
    controller.edit_builtin("")
    assert controller.tokens["editor"] == {}


def test_a_custom_token_has_its_value_map_too(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.add_token()
    editor = controller.tokens["editor"]
    assert editor["index"] == 0
    assert editor["maps"] == [{"read": "", "written": ""}]


def test_the_untagged_language_is_set_and_its_problem_shown(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert controller.untagged == {"value": "", "label": "as is", "problem": ""}
    controller.set_untagged_language(" tr ")
    assert controller.untagged["value"] == "tr"
    assert controller.untagged["label"] == "Turkish (tr)"
    assert controller.batches.own(controller.workspace.key)  # type: ignore[arg-type]
    controller.set_untagged_language("not a language")
    assert "not a language" in controller.untagged["problem"]


def test_a_hand_written_rule_can_be_deleted_a_choice_cannot(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    tracks = controller.workspace.tracks()
    written = TrackRule(match=TrackMatch(languages=["tur"]), verdict=Verdict.DROP)
    controller.workspace.set_tracks(replace(tracks, rules=[*tracks.rules, written]))
    assert len(controller.rules) == 2
    controller.remove_rule(0)  # the commentary choice stays: it is undone on its track
    assert len(controller.rules) == 2
    controller.remove_rule(1)
    assert len(controller.rules) == 1
    assert controller.rules[0]["from_choice"]


def test_the_shortcuts_name_the_keys_that_move_tracks_in_the_order(controller: WindowController) -> None:
    entries = {entry["text"]: entry["keys"] for entry in controller.settings.shortcuts}
    assert entries["Tracks: move the focused column in the track order"] == ["Ctrl+Left", "Ctrl+Right"]
    assert entries["Movie Overview: move the focused track card in the track order"] == ["Ctrl+Up", "Ctrl+Down"]
