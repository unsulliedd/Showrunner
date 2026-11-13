from __future__ import annotations

from showrunner.stages.scan.pairing import Match, name_keys, pair


def pair_names(videos: list[str], subtitles: list[str], sizes: list[int] | None = None) -> list[Match]:
    return pair(name_keys(videos), name_keys(subtitles), sizes or [1] * len(subtitles))


def test_title_wins_over_episode_number() -> None:
    # The video follows the airing order, the subtitle the production order.
    videos = [
        "Show (1992) S03E04 Snowfall",
        "Show (1992) S03E05 Market Day",
        "Show (1992) S03E06 Quiet Evening",
    ]
    subtitles = [
        "Show - 304 - Market Day",
        "Show - 305 - Snowfall",
        "Show - 306 - Quiet Evening",
    ]
    assert [(m.video, m.subtitle) for m in pair_names(videos, subtitles)] == [(0, 1), (1, 0), (2, 2)]


def test_number_pairs_names_without_a_title() -> None:
    videos = ["Show (1992) S14E04 Some Title", "Show (1992) S14E05 Other Name"]
    subtitles = ["Show.S14E05.720p.HDTV.x264-GROUP", "Show.S14E04.720p.HDTV.x264-GROUP"]
    assert [(m.video, m.subtitle) for m in pair_names(videos, subtitles)] == [(0, 1), (1, 0)]


def test_all_three_number_spellings_are_the_same_episode() -> None:
    videos = ["Show S09E05 Alpha"]
    for subtitle in ("Show.S09E05", "Show - 9x05", "Show - 905"):
        assert [(m.video, m.subtitle) for m in pair_names(videos, [subtitle])] == [(0, 0)]


def test_a_file_that_fits_nothing_is_not_paired() -> None:
    videos = ["Show S01E01 Alpha"]
    assert pair_names(videos, ["Completely Other Thing"]) == []


def test_equal_scores_are_kept_as_alternatives_and_the_larger_file_is_attached() -> None:
    videos = ["Show (1992) S14E04 Title"]
    subtitles = ["Show.S14E04.720p.HDTV.x264-GROUP (Alpha)", "Show.S14E04.720p.HDTV.x264-GROUP (Other)"]
    assert pair_names(videos, subtitles, sizes=[100, 300]) == [Match(0, 1, alternatives=(0,))]


def test_a_subtitle_goes_to_one_video_only() -> None:
    videos = ["Show S01E01 Alpha", "Show S01E02 Beta"]
    matches = pair_names(videos, ["Show S01E01 Alpha"])
    assert matches == [Match(0, 0)]


def test_an_alternative_that_a_later_match_took_is_no_alternative() -> None:
    # Both videos fit both files equally; the first video sees the second file as an alternative until the
    # second video takes it.
    videos = ["Show S01E01 720p", "Show S01E01 1080p"]
    subtitles = ["Show S01E01 a", "Show S01E01 b"]
    assert pair_names(videos, subtitles, sizes=[2, 1]) == [Match(0, 0), Match(1, 1)]
