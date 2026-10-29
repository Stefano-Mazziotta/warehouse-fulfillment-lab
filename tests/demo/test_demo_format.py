from demo_format import exception_summary, heading, render_table, shorten


def test_table_aligns_columns_to_the_widest_cell():
    text = render_table(["event", "status"], [["OrderAllocated", "PENDING"], ["X", "PUBLISHED"]])

    assert text.splitlines() == [
        "event           status",
        "--------------  ---------",
        "OrderAllocated  PENDING",
        "X               PUBLISHED",
    ]


def test_an_empty_table_says_so_instead_of_printing_a_bare_header():
    assert render_table(["event", "status"], []) == "(no rows)"


def test_none_is_shown_as_a_dash():
    assert "-" in render_table(["tracking"], [[None]]).splitlines()[-1]


def test_shorten_marks_the_cut():
    assert shorten("abcdefghij", 6) == "abcde…"
    assert shorten("abc", 6) == "abc"


def test_heading_underlines_with_the_same_width():
    first, second = heading("Phase 1").splitlines()[-2:]

    assert first == "Phase 1" and second == "=" * len("Phase 1")


def test_exception_summary_skips_the_trailing_background_hint():
    traceback = (
        "Traceback (most recent call last):\n  File \"x.py\", line 1\n"
        "psycopg.errors.UndefinedTable: relation \"orders\" does not exist\n\n"
        "The above exception was the direct cause of the following exception:\n\n"
        "sqlalchemy.exc.ProgrammingError: (psycopg.errors.UndefinedTable) relation \"orders\" does not exist\n"
        "(Background on this error at: https://sqlalche.me/e/20/f405)")

    assert exception_summary(traceback).startswith("sqlalchemy.exc.ProgrammingError")


def test_exception_summary_falls_back_to_the_last_line():
    assert exception_summary("boom\nlast words") == "last words"
    assert exception_summary("") == ""
