import pytest

from showrunner.ui.quick.window_state import WindowState, decode, encode, fit

PRIMARY = (0, 0, 1920, 1040)
SECOND = (1920, 0, 1280, 1000)


def test_a_state_survives_the_text_it_is_kept_as() -> None:
    state = WindowState((-30, 12, 1440, 900), maximized=True)
    assert decode(encode(state)) == state


@pytest.mark.parametrize("text", ["", "g", "1,2,3", "1,2,3,4,5,6", "1,2,0,4,0", "1,2,300,400,2", "a,2,3,4,0"])
def test_a_damaged_text_is_no_state(text: str) -> None:
    assert decode(text) is None


def test_a_window_on_a_screen_stays_where_it_was() -> None:
    state = WindowState((2000, 100, 1000, 700))
    assert fit(state, [PRIMARY, SECOND]) == state


def test_a_window_whose_screen_is_gone_is_centred_on_the_primary_one() -> None:
    fitted = fit(WindowState((2000, 100, 1000, 700), maximized=True), [PRIMARY])
    assert fitted == WindowState((460, 170, 1000, 700), maximized=True)


def test_a_window_hanging_off_the_screen_is_moved_inside_it() -> None:
    assert fit(WindowState((1500, 800, 800, 600)), [PRIMARY]) == WindowState((1120, 440, 800, 600))


def test_a_window_with_its_title_bar_above_the_screen_is_brought_down() -> None:
    assert fit(WindowState((100, -30, 800, 600)), [PRIMARY]) == WindowState((100, 0, 800, 600))


def test_a_window_with_no_part_of_its_title_bar_on_a_screen_is_centred() -> None:
    assert fit(WindowState((100, -500, 800, 600)), [PRIMARY]) == WindowState((560, 220, 800, 600))


def test_a_window_larger_than_the_screen_is_shrunk() -> None:
    assert fit(WindowState((0, 0, 3000, 2000)), [PRIMARY]) == WindowState((0, 0, 1920, 1040))


def test_no_screens_leave_the_state_alone() -> None:
    assert fit(WindowState((0, 0, 100, 100)), []) is None
