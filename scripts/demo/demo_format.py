import re
from collections.abc import Sequence

_EXCEPTION_LINE = re.compile(r"[A-Za-z_][\w.]*(Error|Exception)\b")


def heading(text: str) -> str:
    return f"\n{text}\n{'=' * len(text)}"


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    if not rows:
        return "(no rows)"
    cells = [[("-" if value is None else str(value)) for value in row] for row in rows]
    widths = [max(len(headers[i]), *(len(row[i]) for row in cells)) for i in range(len(headers))]
    line = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths)).rstrip()  # noqa: E731
    return "\n".join([line(headers), line(["-" * w for w in widths]), *(line(row) for row in cells)])


def exception_summary(traceback_text: str) -> str:
    """The most useful single line of a traceback: the last 'SomethingError: ...' line.

    Chained tracebacks end with the outermost exception and often a trailing '(Background on
    this error ...)' hint, so the last line alone is rarely the cause.
    """
    lines = [line for line in traceback_text.splitlines() if line.strip()]
    for line in reversed(lines):
        if _EXCEPTION_LINE.match(line):
            return shorten(line, 200)
    return shorten(lines[-1], 200) if lines else ""
