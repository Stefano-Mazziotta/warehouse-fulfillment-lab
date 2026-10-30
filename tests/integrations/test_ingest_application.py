"""Ingest rules with fake ports: no database, no broker."""
import pytest

from integrations.application.receive_channel_event import ReceiveChannelEvent
from integrations.domain.channel_event import ChannelEvent
from integrations.domain.ingest_outcome import IngestOutcome as Outcome
from orders.domain import OrderKey, OrderLine, Order

from channel_support import SOURCE, InMemoryIngestStore, channel_order


@pytest.fixture
def store():
    return InMemoryIngestStore()


@pytest.fixture
def receive(store):
    return ReceiveChannelEvent(store.transaction, SOURCE).execute


def event(order, event_id="evt-1"):
    return ChannelEvent(event_id, order)


def test_webhook_creates_the_wms_order_and_records_the_event(store, receive):
    assert receive(event(channel_order())) is Outcome.CREATED
    created = store.orders[OrderKey("owner", "c1")]
    assert (created.warehouse_id, created.lines) == ("w1", (OrderLine("l1", "sku", 1),))
    assert store.events["evt-1"]["status"] == "PROCESSED"


def test_duplicate_channel_event_is_processed_once(store, receive):
    assert receive(event(channel_order())) is Outcome.CREATED
    assert receive(event(channel_order())) is Outcome.DUPLICATE_EVENT
    assert len(store.orders) == 1


def test_new_event_for_the_same_content_is_an_idempotent_no_op(store, receive):
    receive(event(channel_order(), "evt-1"))
    assert receive(event(channel_order(minutes=3), "evt-2")) is Outcome.ALREADY_KNOWN
    assert len(store.orders) == 1


def test_same_version_with_different_content_is_a_conflict_and_never_overwrites(store, receive):
    receive(event(channel_order(lines=(("l1", "sku", 1),)), "evt-1"))
    different = channel_order(lines=(("l1", "sku", 9),))
    assert receive(event(different, "evt-2")) is Outcome.CONFLICT
    assert store.orders[OrderKey("owner", "c1")].lines == (OrderLine("l1", "sku", 1),)
    assert store.events["evt-2"]["status"] == "FAILED"
    assert "version 1" in store.events["evt-2"]["detail"]


def test_older_version_arriving_after_a_newer_one_is_ignored(store, receive):
    receive(event(channel_order(version=2, minutes=2), "evt-2"))
    stale = channel_order(version=1, minutes=1, lines=(("l1", "sku", 9),))
    assert receive(event(stale, "evt-1")) is Outcome.STALE_IGNORED
    assert store.versions[(SOURCE, "owner", "c1")].version == 2
    assert store.events["evt-1"]["status"] == "PROCESSED"


def test_newer_version_with_the_same_content_only_advances_the_known_version(store, receive):
    receive(event(channel_order(version=1), "evt-1"))
    assert receive(event(channel_order(version=2, minutes=1), "evt-2")) is Outcome.ALREADY_KNOWN
    assert store.versions[(SOURCE, "owner", "c1")].version == 2


def test_newer_version_with_different_content_is_surfaced_not_applied(store, receive):
    # Amending an order the warehouse may already be allocating is a business decision.
    receive(event(channel_order(version=1), "evt-1"))
    amended = channel_order(version=2, minutes=1, lines=(("l1", "sku", 4),))
    assert receive(event(amended, "evt-2")) is Outcome.CONFLICT
    assert store.versions[(SOURCE, "owner", "c1")].version == 1
    assert store.orders[OrderKey("owner", "c1")].lines == (OrderLine("l1", "sku", 1),)


def test_existing_wms_order_with_another_payload_is_a_conflict(store, receive):
    other = Order(OrderKey("owner", "c1"), "w1", (OrderLine("l1", "sku", 7),))
    with store.transaction() as transaction:
        transaction.create_order(other)
    assert receive(event(channel_order())) is Outcome.CONFLICT
    assert store.orders[other.key] == other
    assert not store.versions


def test_owners_are_isolated(store, receive):
    receive(event(channel_order(client="a"), "evt-a"))
    receive(event(channel_order(client="b"), "evt-b"))
    assert {key.client_id for key in store.orders} == {"a", "b"}


def test_processing_failure_keeps_the_raw_event_and_a_retry_succeeds(store, receive):
    store.fail_on = "c1"
    with pytest.raises(RuntimeError):
        receive(event(channel_order()))
    # Persist-then-process: the event survives, the inbox row and the order do not.
    assert store.events["evt-1"]["status"] == "RECEIVED"
    assert not store.inbox and not store.orders
    store.fail_on = None
    assert receive(event(channel_order())) is Outcome.CREATED
    assert store.events["evt-1"]["status"] == "PROCESSED"


def test_reconciliation_events_of_tenants_that_differ_by_the_delimiter_both_create_their_orders(store, receive):
    first = ChannelEvent.for_reconciliation(channel_order("c", client="a:b"))
    second = ChannelEvent.for_reconciliation(channel_order("b:c", client="a"))
    assert first.event_id != second.event_id
    assert receive(first) is Outcome.CREATED
    assert receive(second) is Outcome.CREATED
    assert set(store.orders) == {OrderKey("a:b", "c"), OrderKey("a", "b:c")}
    assert first.event_id == ChannelEvent.for_reconciliation(channel_order("c", client="a:b")).event_id
