"""Pure verdict computations: the arithmetic behind each drill's pass/fail checks."""
import json
from collections import Counter
from collections.abc import Sequence


def exactly_one_winner(results: Sequence[bool]) -> bool:
    return sum(results) == 1


def never_regressed(stages: Sequence[int]) -> bool:
    return all(later >= earlier for earlier, later in zip(stages, stages[1:]))


def tally(outcomes: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(outcomes).items()))


def warnings_allowed(count: int, elapsed_seconds: float, *, window_seconds: float) -> bool:
    """One throttled warning per window: at least one (the failure was reported), never one per call."""
    return 1 <= count <= 1 + int(elapsed_seconds // window_seconds)


def count_cache_warnings(log_lines: Sequence[str]) -> int:
    count = 0
    for line in log_lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # tracebacks and werkzeug lines are not JSON
        if isinstance(entry, dict) and entry.get("logger") == "orders.cache" \
                and "cache unavailable" in str(entry.get("message", "")):
            count += 1
    return count
