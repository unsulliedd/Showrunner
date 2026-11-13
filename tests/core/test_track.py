import dataclasses

import pytest

from showrunner.core.track import Track, TrackFlags, TrackKind, VideoProperties


def test_property_group_of_another_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="video properties set on a track of kind audio"):
        Track(1, TrackKind.AUDIO, video=VideoProperties())


def test_defaults() -> None:
    track = Track(0, TrackKind.AUDIO)
    assert track.flags == TrackFlags()
    assert not any(dataclasses.astuple(track.flags))
    assert track.language is None


def test_replace_copies_a_track() -> None:
    track = Track(3, TrackKind.SUBTITLE, flags=TrackFlags(forced=True))
    forced_off = dataclasses.replace(track, flags=dataclasses.replace(track.flags, forced=False))
    assert track.flags.forced
    assert not forced_off.flags.forced
