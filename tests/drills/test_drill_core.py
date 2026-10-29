import pytest

from drill_core import (
    Check, Drill, DrillFailure, Explanation, Outcome, make_pause, run_drill, select_drills,
)

EXPLANATION = Explanation(
    invariant="the invariant", mechanism="the mechanism", without="what breaks", trade_off="the cost")


def make_drill(number=1, act=None):
    return Drill(
        number, f"drill-{number}", f"Title {number}", "the scenario", "What will happen?", EXPLANATION,
        act or (lambda context: Outcome((Check("it held", True),))))


def run(drill, *, log=None):
    log = [] if log is None else log
    ok = run_drill(drill, object(), pause=lambda: log.append("PAUSE"), out=log.append)
    return ok, log


def test_the_question_is_shown_before_the_pause_and_the_answer_only_after_the_action():
    log = []
    drill = make_drill(act=lambda context: (log.append("ACT"), Outcome((Check("held", True),)))[1])

    ok, log = run(drill, log=log)

    text = "\n".join(log)
    assert ok is True
    assert log.index("PAUSE") > next(i for i, line in enumerate(log) if "What will happen?" in line)
    assert log.index("ACT") > log.index("PAUSE")
    assert text.index("the mechanism") > text.index("[ok] held")
    assert "the invariant" not in text.split("PAUSE")[0] and "the mechanism" not in text.split("ACT")[0]


def test_the_pause_happens_exactly_once_per_drill():
    _, log = run(make_drill())

    assert log.count("PAUSE") == 1


def test_a_failed_check_fails_the_drill_but_still_reveals_the_explanation():
    drill = make_drill(act=lambda context: Outcome((Check("held", True), Check("oversold", False))))

    ok, log = run(drill)

    text = "\n".join(log)
    assert ok is False
    assert "[ok] held" in text and "[FAIL] oversold" in text
    assert "what breaks" in text


def test_an_expected_infrastructure_failure_becomes_a_failed_check_not_a_traceback():
    def act(context):
        raise DrillFailure("the broker never answered")

    ok, log = run(make_drill(act=act))

    assert ok is False
    assert any("[FAIL] the broker never answered" in line for line in log)


def test_unexpected_errors_are_not_swallowed():
    def act(context):
        raise KeyError("a bug")

    with pytest.raises(KeyError):
        run(make_drill(act=act))


def test_a_drill_with_no_checks_cannot_pass():
    ok, _ = run(make_drill(act=lambda context: Outcome(())))

    assert ok is False


def test_the_heading_names_the_drill_number_and_title():
    _, log = run(make_drill(number=4))

    assert any("Drill 4: Title 4" in line for line in log)


CATALOG = [make_drill(number) for number in range(1, 9)]


@pytest.mark.parametrize("selector, expected", [("3", [3]), ("all", list(range(1, 9))), ("08", [8])])
def test_select_drills_by_number_or_all(selector, expected):
    assert [d.number for d in select_drills(CATALOG, selector)] == expected


@pytest.mark.parametrize("selector", ["0", "9", "x", "", "1,2"])
def test_select_drills_rejects_anything_else_and_lists_the_valid_choices(selector):
    with pytest.raises(ValueError, match="1-8"):
        select_drills(CATALOG, selector)


def test_pause_waits_for_enter_only_when_interactive():
    prompts = []

    make_pause(False, input_fn=prompts.append)()
    assert prompts == []

    make_pause(True, input_fn=prompts.append)()
    assert len(prompts) == 1 and "Enter" in prompts[0]
