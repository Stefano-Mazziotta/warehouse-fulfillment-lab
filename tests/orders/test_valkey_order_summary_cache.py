"""The adapter against a real Valkey, isolated per test by a unique key prefix."""
import time
from uuid import uuid4

import pytest
import valkey

from orders.application.cache_unavailable import CacheUnavailable
from orders.application.order_summary import OrderSummary
from orders.domain import OrderStatus
from orders.infrastructure.valkey_order_summary_cache import ValkeyOrderSummaryCache

SUMMARY = OrderSummary("o1", "w1", OrderStatus.ALLOCATED)


@pytest.fixture
def cache(valkey_url):
    return ValkeyOrderSummaryCache(
        valkey_url, ttl_seconds=30, key_prefix=f"lab-test:{uuid4().hex}:")


def test_miss_returns_none(cache):
    assert cache.get("owner", "o1") is None


def test_put_then_get_round_trips_the_summary(cache):
    cache.put("owner", SUMMARY)
    assert cache.get("owner", "o1") == SUMMARY


def test_entries_are_scoped_to_the_owner(cache):
    cache.put("owner", SUMMARY)
    assert cache.get("someone-else", "o1") is None


def test_invalidate_removes_the_entry(cache):
    cache.put("owner", SUMMARY)
    cache.invalidate("owner", "o1")
    assert cache.get("owner", "o1") is None


def test_entry_expires_after_ttl(valkey_url):
    short = ValkeyOrderSummaryCache(
        valkey_url, ttl_seconds=1, key_prefix=f"lab-test:{uuid4().hex}:")
    short.put("owner", SUMMARY)
    time.sleep(1.2)
    assert short.get("owner", "o1") is None


def test_unreadable_payload_is_a_miss_not_an_error(valkey_url):
    prefix = f"lab-test:{uuid4().hex}:"
    cache = ValkeyOrderSummaryCache(valkey_url, ttl_seconds=30, key_prefix=prefix)
    valkey.Valkey.from_url(valkey_url).set(f"{prefix}owner:o1", b"not json")
    assert cache.get("owner", "o1") is None


@pytest.mark.parametrize("operation", ["get", "put", "invalidate"])
def test_unreachable_server_raises_cache_unavailable_quickly(operation):
    # Nothing listens on port 1; a connection refusal must surface as the port's own error.
    cache = ValkeyOrderSummaryCache("valkey://127.0.0.1:1/0", ttl_seconds=30)
    started = time.monotonic()
    with pytest.raises(CacheUnavailable):
        if operation == "get":
            cache.get("owner", "o1")
        elif operation == "put":
            cache.put("owner", SUMMARY)
        else:
            cache.invalidate("owner", "o1")
    assert time.monotonic() - started < 2


def test_blackholed_server_times_out_instead_of_hanging():
    import socket
    # Accepts the TCP connection but never answers: the socket timeout is what saves the caller.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        cache = ValkeyOrderSummaryCache(
            f"valkey://127.0.0.1:{silent.getsockname()[1]}/0", ttl_seconds=30, timeout_seconds=0.2)
        started = time.monotonic()
        with pytest.raises(CacheUnavailable):
            cache.get("owner", "o1")
        assert time.monotonic() - started < 2


@pytest.mark.parametrize("first, second", [
    (("a:b", "c"), ("a", "b:c")),
    (("a%3Ab", "c"), ("a:b", "c")),
])
def test_distinct_owner_and_order_pairs_never_share_a_key(first, second):
    cache = ValkeyOrderSummaryCache("valkey://127.0.0.1:1/0", ttl_seconds=30)

    assert cache._key(*first) != cache._key(*second)


def test_an_owner_never_reads_another_owners_summary_through_a_delimiter(cache):
    cache.put("a:b", OrderSummary("c", "w1", OrderStatus.ALLOCATED))

    assert cache.get("a", "b:c") is None
    assert cache.get("a:b", "c") is not None


def test_invalidate_removes_an_entry_whose_ids_contain_the_delimiter(cache):
    cache.put("a:b", OrderSummary("c:d", "w1", OrderStatus.ALLOCATED))
    cache.invalidate("a:b", "c:d")

    assert cache.get("a:b", "c:d") is None
