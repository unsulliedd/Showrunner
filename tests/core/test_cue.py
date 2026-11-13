import dataclasses

import pytest

from showrunner.core.cue import Cue


def test_midpoint() -> None:
    assert Cue(1.0, 3.0, "Hi").midpoint == 2.0


def test_cue_is_immutable_and_copied_with_replace() -> None:
    cue = Cue(1.0, 3.0, "Hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cue.start = 2.0  # type: ignore[misc]
    assert dataclasses.replace(cue, start=2.0).midpoint == 2.5
