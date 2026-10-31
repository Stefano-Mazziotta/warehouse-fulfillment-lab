"""Both fake channels must honor the same contract the reconciler relies on."""
import pytest

from integrations.domain.channel_cursor import ChannelCursor
from integrations.infrastructure.channel_webhooks import ChannelWebhooks
from integrations.infrastructure.in_memory_sales_channel import InMemorySalesChannel
from integrations.infrastructure.postgres_fake_sales_channel import PostgresFakeSalesChannel

from channel_support import T0, at, ChannelOrderLine

LINES = (ChannelOrderLine("l1", "sku", 1),)


@pytest.fixture(params=["memory", "postgres"])
def channel(request):
    webhooks = ChannelWebhooks()
    if request.param == "memory":
        return InMemorySalesChannel(webhooks, clock=lambda: T0)
    engine = request.getfixturevalue("orders_database")
    PostgresFakeSalesChannel.install(engine)
    return PostgresFakeSalesChannel(engine, webhooks, clock=lambda: T0)


def place(channel, order_id, minutes, client="owner"):
    return channel.upsert(client, order_id, "w1", LINES, updated_at=at(minutes))


def test_orders_are_listed_by_updated_at_then_id_and_paged_with_a_cursor(channel):
    for order_id, minutes in [("b", 2), ("a", 2), ("z", 1), ("c", 3)]:
        place(channel, order_id, minutes)
    first = channel.list_orders_updated_since("owner", None, 3)
    assert [order.channel_order_id for order in first.orders] == ["z", "a", "b"]
    assert first.has_more is True
    second = channel.list_orders_updated_since("owner", first.next_cursor, 3)
    assert [order.channel_order_id for order in second.orders] == ["c"]
    assert second.has_more is False


def test_cursor_is_exclusive_and_owner_scoped(channel):
    place(channel, "a", 1)
    place(channel, "other", 1, client="someone-else")
    page = channel.list_orders_updated_since("owner", None, 10)
    assert [order.channel_order_id for order in page.orders] == ["a"]
    assert channel.list_orders_updated_since("owner", ChannelCursor(at(1), "a"), 10).orders == ()


def test_each_update_bumps_the_version_monotonically(channel):
    place(channel, "a", 1)
    place(channel, "a", 2)
    (order,) = channel.list_orders_updated_since("owner", None, 10).orders
    assert (order.version, order.updated_at) == (2, at(2))


def test_dropped_webhooks_are_not_delivered_but_the_order_is_still_listed(channel):
    delivered = []
    channel.webhooks.subscribe(delivered.append)
    channel.webhooks.drop = True
    event = place(channel, "a", 1)
    assert delivered == [] and event.order.channel_order_id == "a"
    channel.webhooks.drop = False
    place(channel, "b", 2)
    assert [e.order.channel_order_id for e in delivered] == ["b"]
    assert len(channel.list_orders_updated_since("owner", None, 10).orders) == 2
