import pytest

from drill_verdicts import exactly_one_winner, never_regressed, tally, warnings_allowed


def test_exactly_one_winner_among_workers():
    assert exactly_one_winner([True, False]) is True
    assert exactly_one_winner([False, True, False]) is True


@pytest.mark.parametrize("results", [[], [False, False], [True, True], [True, True, False]])
def test_zero_or_several_winners_is_an_oversell_or_a_lost_order(results):
    assert exactly_one_winner(results) is False


def test_stage_never_regresses_when_it_only_holds_or_grows():
    assert never_regressed([4, 4, 4, 4]) is True
    assert never_regressed([1, 2, 2, 4]) is True
    assert never_regressed([]) is True


def test_a_stage_that_goes_back_is_a_regression():
    assert never_regressed([4, 3]) is False
    assert never_regressed([1, 4, 2]) is False


def test_tally_counts_outcomes_in_a_stable_order():
    assert tally(["DUPLICATE_EVENT", "CREATED", "DUPLICATE_EVENT"]) == {"CREATED": 1, "DUPLICATE_EVENT": 2}


@pytest.mark.parametrize("count, elapsed, ok", [
    (1, 0.4, True), (1, 4.9, True), (0, 1.0, False), (2, 1.0, False), (2, 5.1, True), (3, 5.1, False),
    (2, 10.5, True), (4, 10.5, False)])
def test_throttled_warnings_are_at_least_one_and_at_most_one_per_window(count, elapsed, ok):
    assert warnings_allowed(count, elapsed, window_seconds=5.0) is ok


def test_cache_warnings_are_counted_from_json_log_lines_only():
    import json
    from drill_verdicts import count_cache_warnings

    lines = [
        json.dumps({"logger": "orders.cache", "level": "WARNING", "message": "cache unavailable; reads fall back to PostgreSQL"}),
        json.dumps({"logger": "orders.cache", "level": "WARNING", "message": "cache unavailable; reads fall back to PostgreSQL"}),
        json.dumps({"logger": "messaging.consumer", "level": "WARNING", "message": "handler failed"}),
        "Traceback (most recent call last):",
        "",
    ]

    assert count_cache_warnings(lines) == 2
