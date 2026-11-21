from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import Episode, Movie
from showrunner.core.options.registry import REGISTRY
from showrunner.stages.scan import ScanOptions, scan
from showrunner.stages.scan.walk import walk_files

Make = Callable[..., Path]
TURKISH = Language("tur")


def names(item) -> list[str]:
    return [s.path.name for s in item.subtitles]


def test_walk_skips_hidden_and_work_folders_and_lists_each_file_once(make: Make, tmp_path: Path) -> None:
    keep = make("Show/Season 1/a.mkv")
    make(".showrunner/work/b.mkv")
    make("Show/.hidden/c.mkv")
    make("Show/.DS_Store")
    assert list(walk_files([tmp_path, keep])) == [keep]


def test_walk_enters_a_hidden_folder_that_was_dropped(make: Make, tmp_path: Path) -> None:
    video = make(".dropped/a.mkv")
    assert list(walk_files([tmp_path / ".dropped"])) == [video]


def test_tv_library_with_season_folders_sorted_naturally(make: Make, tmp_path: Path) -> None:
    for season in (10, 2):
        make(f"Show (2010)/Season {season}/Show (2010) S{season:02}E01 Pilot.mkv")
        make(f"Show (2010)/Season {season}/Show (2010) S{season:02}E01 Pilot.en.srt")
    result = scan([tmp_path])
    assert [i.identity for i in result.items] == [
        Episode("Show", 2, 1, 2010, "Pilot"),
        Episode("Show", 10, 1, 2010, "Pilot"),
    ]
    assert all(i.file.container == "mkv" and i.file.size == 1 for i in result.items)
    assert [names(i) for i in result.items] == [
        ["Show (2010) S02E01 Pilot.en.srt"],
        ["Show (2010) S10E01 Pilot.en.srt"],
    ]
    assert result.unpaired == ()
    assert result.alternatives == ()


def test_airing_order_video_pairs_with_production_order_subtitle_by_title(make: Make, tmp_path: Path) -> None:
    for code, title in ((4, "Snowfall"), (5, "Market Day"), (6, "Quiet Evening")):
        make(f"S03/Show (1992) S03E{code:02} {title}.mkv")
        make(f"S03/Show - 3{code - 1:02} - {title}.tr.srt")  # one number lower than the video
    result = scan([tmp_path])
    for item in result.items:
        episode = item.identity
        assert isinstance(episode, Episode)
        assert names(item) == [f"Show - 3{episode.episode - 1:02} - {episode.episode_title}.tr.srt"]
        assert item.subtitles[0].language == TURKISH


def test_untagged_turkish_text_in_a_windows_1254_file_is_detected(
    make: Make, tmp_path: Path, turkish_cp1254: bytes
) -> None:
    make("Show S09E05 The Long Road.mkv")
    make("Show - 9x05 - The Long Road.srt", turkish_cp1254)
    (item,) = scan([tmp_path]).items
    assert item.subtitles[0].language == TURKISH


def test_untagged_english_text_is_detected_and_a_tag_is_not_overruled(
    make: Make, tmp_path: Path, english_utf8: bytes
) -> None:
    make("Movie (2001).mkv")
    make("Movie (2001).srt", english_utf8)
    make("Movie (2001).tr.srt", english_utf8)  # the tag says Turkish, whatever the text is
    (item,) = scan([tmp_path]).items
    assert {s.path.name: s.language for s in item.subtitles} == {
        "Movie (2001).srt": Language("eng"),
        "Movie (2001).tr.srt": TURKISH,
    }


def test_detection_can_be_switched_off(make: Make, tmp_path: Path, turkish_cp1254: bytes) -> None:
    make("Show S01E01.mkv")
    make("Show S01E01.srt", turkish_cp1254)
    (item,) = scan([tmp_path], ScanOptions(detect_untagged_languages=False)).items
    assert item.subtitles[0].language is None


def test_two_candidates_for_one_episode_stay_visible(make: Make, tmp_path: Path) -> None:
    make("S14/Show (1992) S14E04 Title.mkv")
    make("S14/Show.S14E04.720p.HDTV.x264-GROUP (Bravo).srt", b"x" * 10)
    make("S14/Show.S14E04.720p.HDTV.x264-GROUP (Other).srt", b"x" * 20)
    result = scan([tmp_path], ScanOptions(detect_untagged_languages=False))
    (item,) = result.items
    assert names(item) == ["Show.S14E04.720p.HDTV.x264-GROUP (Other).srt"]
    ((alternatives,),) = [(a,) for a in result.alternatives]
    assert alternatives.video == item.file.path
    assert [s.path.name for s in alternatives.subtitles] == ["Show.S14E04.720p.HDTV.x264-GROUP (Bravo).srt"]
    assert result.unpaired == ()


def test_one_video_takes_one_file_per_language_and_flag(make: Make, tmp_path: Path) -> None:
    make("Movie (2010).mkv")
    for tag in ("en", "tr", "en.forced", "tr.sdh"):
        make(f"Movie (2010).{tag}.srt")
    (item,) = scan([tmp_path]).items
    assert sorted((s.language.ietf, s.forced, s.sdh) for s in item.subtitles if s.language) == [
        ("en", False, False),
        ("en", True, False),
        ("tr", False, False),
        ("tr", False, True),
    ]


def test_unpaired_subtitles_and_folders_without_videos_stay_in_the_result(make: Make, tmp_path: Path) -> None:
    make("Show S01E01 Bravo.mkv")
    make("Show S01E01 Bravo.en.srt")
    make("Unrelated Thing.en.srt")
    make("Extras/Making Of.en.srt")
    result = scan([tmp_path])
    assert [s.path.name for s in result.unpaired] == ["Making Of.en.srt", "Unrelated Thing.en.srt"]


def test_movie_in_its_own_folder_with_the_year_in_the_folder_name(make: Make, tmp_path: Path) -> None:
    make("The Example (1999)/example.1080p.mkv")
    make("The Example (1999)/example.1080p.en.srt")
    make("Bravo (1995)/bravo.mkv")
    result = scan([tmp_path])
    assert [(i.identity, names(i)) for i in result.items] == [
        (Movie("Bravo", 1995), []),
        (Movie("The Example", 1999), ["example.1080p.en.srt"]),
    ]


def test_many_movies_in_one_folder_pair_by_name(make: Make, tmp_path: Path) -> None:
    for title in ("Bravo (1995)", "Alpha (1995)", "Delta (1998)"):
        make(f"Movies/{title}.1080p.mkv")
        make(f"Movies/{title}.tr.srt")
    result = scan([tmp_path])
    assert [(i.identity, names(i)) for i in result.items] == [
        (Movie("Alpha", 1995), ["Alpha (1995).tr.srt"]),
        (Movie("Bravo", 1995), ["Bravo (1995).tr.srt"]),
        (Movie("Delta", 1998), ["Delta (1998).tr.srt"]),
    ]
    assert result.unpaired == ()


def test_subs_folder_beside_the_videos_counts_as_their_folder(make: Make, tmp_path: Path) -> None:
    make("Show/Season 1/Show S01E01 Bravo.mkv")
    make("Show/Season 1/Subs/Show S01E01 Bravo.en.srt")
    (item,) = scan([tmp_path]).items
    assert names(item) == ["Show S01E01 Bravo.en.srt"]


def test_subs_folder_can_be_switched_off_and_its_files_stay_visible(make: Make, tmp_path: Path) -> None:
    make("Show/Season 1/Show S01E01 Bravo.mkv")
    subtitle = make("Show/Season 1/Subs/Show S01E01 Bravo.en.srt")
    result = scan([tmp_path], ScanOptions(subtitle_subfolders=False))
    assert result.items[0].subtitles == ()
    assert [s.path for s in result.unpaired] == [subtitle]


def test_a_dropped_video_file_brings_the_subtitles_beside_it(make: Make) -> None:
    video = make("Show/Show S01E01 Bravo.mkv")
    make("Show/Show S01E01 Bravo.en.srt")
    make("Show/Show S01E02 Beta.mkv")
    make("Show/Show S01E02 Beta.en.srt")  # belongs to a video that was not dropped
    result = scan([video])
    assert [(i.file.path, names(i)) for i in result.items] == [(video, ["Show S01E01 Bravo.en.srt"])]
    assert result.unpaired == ()


def test_idx_and_sub_are_one_subtitle(make: Make, tmp_path: Path) -> None:
    make("Movie (2010).mkv")
    make("Movie (2010).en.idx")
    make("Movie (2010).en.sub")
    (item,) = scan([tmp_path]).items
    assert names(item) == ["Movie (2010).en.idx"]


def test_a_dropped_subtitle_file_alone_is_unpaired(make: Make) -> None:
    subtitle = make("Show S01E01.en.srt")
    result = scan([subtitle])
    assert result.items == ()
    assert [s.path for s in result.unpaired] == [subtitle]


def test_options_are_registered_with_defaults_that_keep_today_behaviour() -> None:
    assert REGISTRY.get("scan") is ScanOptions
    assert ScanOptions() == ScanOptions(detect_untagged_languages=True, subtitle_subfolders=True)
