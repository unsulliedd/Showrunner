from __future__ import annotations

from showrunner.stages.tracks import (
    RuleField,
    RuleProblem,
    RuleProblemKind,
    TrackMatch,
    TrackRule,
    TracksOptions,
    check_rules,
)


def rules(*matches: TrackMatch) -> TracksOptions:
    return TracksOptions(enabled=True, rules=[TrackRule(match=m) for m in matches])


def test_good_rules_have_no_problems() -> None:
    options = rules(
        TrackMatch(languages=["tur", "en", "pt-BR", "und", "English"]),
        TrackMatch(min_channels=6, max_channels=6),
        TrackMatch(min_channels=6),
        TrackMatch(name="^Comm", name_is_regex=True),
        TrackMatch(name="(", name_is_regex=False),
    )
    assert check_rules(options) == []


def test_a_language_that_is_not_one() -> None:
    options = rules(TrackMatch(), TrackMatch(languages=["tur", " egn"]))
    assert check_rules(options) == [
        RuleProblem(1, RuleField.LANGUAGES, RuleProblemKind.NOT_A_LANGUAGE, 0, 4, "egn", entry=1)
    ]


def test_a_channel_range_that_fits_nothing() -> None:
    assert check_rules(rules(TrackMatch(min_channels=6, max_channels=2))) == [
        RuleProblem(0, RuleField.CHANNELS, RuleProblemKind.EMPTY_CHANNEL_RANGE)
    ]


def test_an_invalid_regular_expression_points_at_the_error() -> None:
    (problem,) = check_rules(rules(TrackMatch(name="ab(c", name_is_regex=True)))
    assert (problem.field, problem.kind, problem.start, problem.end) == (
        RuleField.NAME,
        RuleProblemKind.BAD_PATTERN,
        2,
        4,
    )
    assert problem.detail


def test_switched_off_rules_are_checked_too() -> None:
    options = TracksOptions(rules=[TrackRule(enabled=False, match=TrackMatch(languages=["xx1"]))])
    assert [p.rule_index for p in check_rules(options)] == [0]
