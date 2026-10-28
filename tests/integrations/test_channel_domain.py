import pytest

from integrations.domain.channel_cursor import ChannelCursor
from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order_line import ChannelOrderLine
from integrations.domain.channel_order_page import ChannelOrderPage
from integrations.domain.channel_order import ChannelOrder
from integrations.domain.integrations_error import IntegrationsError

from channel_support import at, channel_order


def test_lines_are_canonical_and_content_ignores_version_and_time():
    first = channel_order(lines=(("b", "sku", 2), ("a", "sku", 1)), version=1, minutes=0)
    later = channel_order(lines=(("a", "sku", 1), ("b", "sku", 2)), version=7, minutes=30)
    assert first.content() == later.content()
    assert [line["line_id"] for line in first.content()["lines"]] == ["a", "b"]
    assert first.fingerprint() == later.fingerprint()


def test_payload_round_trips_through_json_types():
    order = channel_order(lines=(("a", "sku", 2),), version=3, minutes=5)
    assert ChannelOrder.from_payload(order.to_payload()) == order


@pytest.mark.parametrize("change", [
    {"version": 0}, {"version": True}, {"client": " "}, {"warehouse": ""}, {"lines": ()},
    {"lines": (("a", "sku", 1), ("a", "sku", 2))}, {"lines": (("a", "sku", 0),)},
])
def test_invalid_channel_orders_are_rejected(change):
    with pytest.raises(IntegrationsError):
        channel_order(**change)


def test_updated_at_must_carry_a_timezone():
    with pytest.raises(IntegrationsError, match="timezone"):
        ChannelOrder("o", "c", "w", (ChannelOrderLine("l", "s", 1),), 1, at(0).replace(tzinfo=None))


def test_cursor_orders_by_time_then_id_and_round_trips_as_a_token():
    early, tie_a, tie_b = ChannelCursor(at(0), "z"), ChannelCursor(at(1), "a"), ChannelCursor(at(1), "b")
    assert early < tie_a < tie_b
    odd = ChannelCursor(at(1), "id|with|bars")
    assert ChannelCursor.from_token(odd.to_token()) == odd


def test_overlap_moves_the_cursor_back_to_before_every_order_at_that_time():
    cursor = ChannelCursor(at(10), "c9").minus(at(10) - at(5))
    assert cursor < ChannelCursor(at(5), "a")
    assert cursor == ChannelCursor(at(5), "")


def test_page_exposes_the_cursor_of_its_last_order():
    page = ChannelOrderPage((channel_order("a", minutes=1), channel_order("b", minutes=2)), True)
    assert page.next_cursor == ChannelCursor(at(2), "b")
    assert ChannelOrderPage((), False).next_cursor is None


def test_reconciliation_event_id_changes_with_version_and_content():
    base = ChannelEvent.for_reconciliation(channel_order(version=1))
    assert base.event_id == ChannelEvent.for_reconciliation(channel_order(version=1, minutes=9)).event_id
    assert base.event_id != ChannelEvent.for_reconciliation(channel_order(version=2)).event_id
    assert base.event_id != ChannelEvent.for_reconciliation(
        channel_order(lines=(("l1", "sku", 5),))).event_id
