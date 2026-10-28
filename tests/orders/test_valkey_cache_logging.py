"""A degraded cache is no longer silent, and a dead one does not flood the log."""
import json

from log_capture_support import capture_logs
from order_cache_support import CountingQueries, FakeClock
from orders.application.caching_order_queries import CachingOrderQueries
from orders.application.order_summary import OrderSummary
from orders.domain import OrderStatus
from orders.infrastructure.valkey_order_summary_cache import ValkeyOrderSummaryCache

CREATED = OrderSummary("o1", "w1", OrderStatus.CREATED)
DEAD_URL = "valkey://:s3cret@127.0.0.1:1/0"  # nothing listens on port 1


def build(clock):
    cache = ValkeyOrderSummaryCache(DEAD_URL, ttl_seconds=30, clock=clock)
    return CachingOrderQueries(CountingQueries([CREATED]), cache, clock=clock, cooldown_seconds=5.0)


def warnings(logs):
    return logs.from_logger("orders.cache")


def test_a_failing_cache_logs_one_warning_per_cooldown_window_not_per_request():
    clock = FakeClock()
    cached = build(clock)
    with capture_logs() as logs:
        for _ in range(50):
            assert cached.get_summary("owner", "o1") == CREATED  # reads still work
        assert len(warnings(logs)) == 1
        clock.now = 5.1
        for _ in range(50):
            cached.get_summary("owner", "o1")
    assert len(warnings(logs)) == 2


def test_the_warning_names_the_operation_and_leaks_no_credentials():
    cached = build(FakeClock())
    with capture_logs() as logs:
        cached.get_summary("owner", "o1")
    (line,) = warnings(logs)
    assert line["level"] == "WARNING" and line["operation"] == "get"
    assert "error_type" in line and "s3cret" not in json.dumps(logs.lines)


def test_invalidation_failures_are_throttled_too():
    clock = FakeClock()
    cache = ValkeyOrderSummaryCache(DEAD_URL, ttl_seconds=30, clock=clock)
    with capture_logs() as logs:
        for _ in range(20):
            try:
                cache.invalidate("owner", "o1")
            except Exception:
                pass
    assert len(warnings(logs)) == 1
