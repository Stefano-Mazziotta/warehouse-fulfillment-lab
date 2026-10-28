import pytest

from order_cache_support import CountingQueries, DownCache, FakeClock, FakeOrderSummaryCache, SwitchableCache
from orders.application.caching_order_queries import CachingOrderQueries
from orders.application.cache_unavailable import CacheUnavailable
from orders.application.order_summary import OrderSummary
from orders.domain import OrderStatus

CREATED = OrderSummary("o1", "w1", OrderStatus.CREATED)


def build(cache, queries=None, **options):
    queries = queries or CountingQueries([CREATED])
    return CachingOrderQueries(queries, cache, **options), queries


def test_miss_reads_postgres_then_populates_the_cache():
    cache = FakeOrderSummaryCache()
    cached, queries = build(cache)
    assert cached.get_summary("owner", "o1") == CREATED
    assert queries.get_summary_calls == 1
    assert cache.entries[("owner", "o1")] == CREATED


def test_hit_is_served_without_touching_postgres():
    cache = FakeOrderSummaryCache()
    cached, queries = build(cache)
    cached.get_summary("owner", "o1")
    assert cached.get_summary("owner", "o1") == CREATED
    assert queries.get_summary_calls == 1


def test_absent_orders_are_not_cached():
    # A negative entry could hide an order created a moment later by another process.
    cache = FakeOrderSummaryCache()
    cached, queries = build(cache, CountingQueries())
    assert cached.get_summary("owner", "missing") is None
    assert cache.entries == {}


def test_entry_invalidated_elsewhere_is_reloaded_from_postgres():
    cache = FakeOrderSummaryCache()
    cached, queries = build(cache)
    cached.get_summary("owner", "o1")
    queries.rows["o1"] = OrderSummary("o1", "w1", OrderStatus.ALLOCATED)
    cache.invalidate("owner", "o1")
    assert cached.get_summary("owner", "o1").status is OrderStatus.ALLOCATED


@pytest.mark.parametrize("error", [CacheUnavailable("down"), TimeoutError(), RuntimeError("boom")])
def test_reads_succeed_from_postgres_when_the_cache_raises(error):
    cached, queries = build(DownCache(error))
    assert cached.get_summary("owner", "o1") == CREATED
    assert queries.get_summary_calls == 1


def test_a_failing_cache_is_skipped_during_the_cooldown_then_probed_again():
    clock, cache = FakeClock(), DownCache()
    cached, _ = build(cache, clock=clock, cooldown_seconds=5.0)
    cached.get_summary("owner", "o1")
    assert cache.attempts == 1
    clock.now = 4.9
    cached.get_summary("owner", "o1")
    assert cache.attempts == 1  # no more timeouts paid while the cache is known to be down
    clock.now = 5.1
    cached.get_summary("owner", "o1")
    assert cache.attempts == 2


def test_recovered_cache_serves_hits_again_after_the_cooldown():
    clock, cache = FakeClock(), SwitchableCache()
    cached, queries = build(cache, clock=clock, cooldown_seconds=5.0)
    cache.down = True
    cached.get_summary("owner", "o1")
    cache.down = False
    clock.now = 6.0
    cached.get_summary("owner", "o1")  # miss: populates
    cached.get_summary("owner", "o1")  # hit
    assert queries.get_summary_calls == 2


def test_lists_and_batches_bypass_the_cache():
    cache = FakeOrderSummaryCache()
    cached, _ = build(cache)
    assert cached.list_summaries("owner", None, 10) == (CREATED,)
    assert cached.lines_for("owner", ["o1"]) == {}
    assert cached.reservations_for("owner", ["o1"]) == {}
    assert cache.calls == []
