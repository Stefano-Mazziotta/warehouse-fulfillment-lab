from datetime import timedelta

import pytest

from messaging.domain.fulfillment_events import (
    order_allocated, order_cancelled, order_packed, order_shipped, picking_completed,
)
from messaging.domain.integration_event import IntegrationEvent
from messaging.domain.messaging_error import MessagingError
from messaging.domain.outbox_message import OutboxMessage
from messaging.domain.outbox_status import OutboxStatus
from messaging.domain.retry_policy import RetryPolicy

from in_memory_messaging import START, event, pending


def test_event_identity_cannot_collide_across_clients_that_differ_by_the_delimiter():
    first = order_allocated("a:b", "c", "w1", [("l1", "sku", 1)])
    second = order_allocated("a", "b:c", "w1", [("l1", "sku", 1)])
    assert first.message_id != second.message_id
    assert first.message_id == order_allocated("a:b", "c", "w1", [("l1", "sku", 1)]).message_id
    assert "%" not in event().message_id  # ordinary identifiers keep their readable form


def test_event_identity_is_stable_per_business_fact():
    assert event().message_id == "OrderAllocated:owner:order"
    assert event().message_id == event().message_id
    assert event(event_type="OrderCancelled").message_id != event().message_id


@pytest.mark.parametrize("field", ["client_id", "aggregate_type", "aggregate_id", "event_type"])
def test_event_rejects_blank_identity(field):
    values = dict(client_id="o", aggregate_type="order", aggregate_id="1", event_type="E", payload={})
    values[field] = " "
    with pytest.raises(MessagingError):
        IntegrationEvent(**values)


def test_fulfillment_events_name_the_five_business_facts():
    events = [
        order_allocated("o", "1", "w", [("a", "sku", 2)]),
        order_cancelled("o", "1"),
        picking_completed("o", "1"),
        order_packed("o", "1", ["box-0"]),
        order_shipped("o", "1", "attempt", "TRACK", ["box-0"]),
    ]
    assert [e.event_type for e in events] == [
        "OrderAllocated", "OrderCancelled", "PickingCompleted", "OrderPacked", "OrderShipped"]
    assert {e.client_id for e in events} == {"o"}
    assert {e.aggregate_type for e in events} == {"order"}
    assert events[0].payload["lines"] == [{"line_id": "a", "sku": "sku", "quantity": 2}]


def test_new_message_is_pending_and_due_immediately():
    message = pending()
    assert (message.status, message.attempt_count, message.last_error) == (
        OutboxStatus.PENDING, 0, None)
    assert message.next_attempt_at == START


def test_backoff_doubles_up_to_the_cap():
    policy = RetryPolicy(max_attempts=10, base_delay=timedelta(seconds=1), max_delay=timedelta(seconds=5))
    assert [policy.delay_after(n).total_seconds() for n in (1, 2, 3, 4, 5)] == [1, 2, 4, 5, 5]


def test_failure_reschedules_then_dies_at_the_limit():
    policy = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=10))
    message = pending()
    first = message.failed("boom", START, policy)
    assert (first.status, first.attempt_count, first.last_error) == (OutboxStatus.PENDING, 1, "boom")
    assert first.next_attempt_at == START + timedelta(seconds=10)
    second = first.failed("boom", START, policy)
    assert second.next_attempt_at == START + timedelta(seconds=20)
    third = second.failed("last", START, policy)
    assert (third.status, third.attempt_count, third.last_error) == (OutboxStatus.DEAD, 3, "last")


def test_published_messages_are_terminal():
    published = pending().published()
    assert published.status == OutboxStatus.PUBLISHED
    with pytest.raises(MessagingError):
        published.failed("late", START, RetryPolicy())
    with pytest.raises(MessagingError):
        published.published()
    assert isinstance(published, OutboxMessage)


def test_retry_policy_rejects_nonsense():
    with pytest.raises(MessagingError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(MessagingError):
        RetryPolicy(base_delay=timedelta(0))
