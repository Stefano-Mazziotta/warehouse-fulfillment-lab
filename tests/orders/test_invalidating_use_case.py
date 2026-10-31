import pytest

from order_cache_support import DownCache, FakeOrderSummaryCache
from orders.application.invalidating_use_case import InvalidatingUseCase
from orders.domain import OrderKey


class Recorder:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail

    def execute(self, key, *rest):
        if self.fail:
            raise self.fail
        return "done"


def first_argument(key, *rest):
    return key


KEY = OrderKey("owner", "o1")


def test_invalidates_the_order_after_the_use_case_succeeds():
    cache = FakeOrderSummaryCache()
    result = InvalidatingUseCase(Recorder(), cache, first_argument).execute(KEY, "extra")
    assert result == "done"
    assert cache.calls == [("invalidate", "owner", "o1")]


def test_invalidates_even_when_the_use_case_fails():
    # A failure after commit (lost response, timeout) may still have changed the order.
    cache = FakeOrderSummaryCache()
    with pytest.raises(ValueError):
        InvalidatingUseCase(Recorder(ValueError("x")), cache, first_argument).execute(KEY)
    assert cache.calls == [("invalidate", "owner", "o1")]


def test_a_down_cache_never_fails_a_committed_mutation():
    cache = DownCache()
    assert InvalidatingUseCase(Recorder(), cache, first_argument).execute(KEY) == "done"
    assert cache.attempts == 1


def test_use_case_error_wins_over_a_down_cache():
    with pytest.raises(ValueError):
        InvalidatingUseCase(Recorder(ValueError("x")), DownCache(), first_argument).execute(KEY)
