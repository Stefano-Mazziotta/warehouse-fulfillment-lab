import pytest

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.inbound_message import InboundMessage

from in_memory_messaging import InMemoryInbox


def message(message_id, event_type="OrderAllocated"):
    return InboundMessage(message_id, event_type, "owner", {"order_id": message_id})


def recording_handler(transaction, inbound):
    transaction.effects.append(inbound.message_id)


def test_first_delivery_runs_the_handler_once():
    inbox = InMemoryInbox()
    consumer = IdempotentConsumer(inbox, "projection", recording_handler)
    assert consumer.handle(message("m1")) is True
    assert inbox.effects == ["m1"]


def test_redelivery_is_a_no_op():
    inbox = InMemoryInbox()
    consumer = IdempotentConsumer(inbox, "projection", recording_handler)
    consumer.handle(message("m1"))
    assert consumer.handle(message("m1")) is False
    assert inbox.effects == ["m1"]


def test_handler_failure_leaves_no_inbox_row_and_is_retryable():
    inbox, fail = InMemoryInbox(), [True]

    def flaky(transaction, inbound):
        transaction.effects.append(inbound.message_id)
        if fail:
            raise RuntimeError("downstream unavailable")

    consumer = IdempotentConsumer(inbox, "projection", flaky)
    with pytest.raises(RuntimeError):
        consumer.handle(message("m1"))
    assert (inbox.seen, inbox.effects) == (set(), [])
    fail.clear()
    assert consumer.handle(message("m1")) is True
    assert inbox.effects == ["m1"]


def test_each_consumer_keeps_its_own_inbox():
    inbox = InMemoryInbox()
    IdempotentConsumer(inbox, "projection", recording_handler).handle(message("m1"))
    assert IdempotentConsumer(inbox, "notifier", recording_handler).handle(message("m1")) is True
    assert inbox.effects == ["m1", "m1"]


def test_out_of_order_delivery_converges_for_an_order_insensitive_handler():
    # Ordering is NOT guaranteed by at-least-once delivery. This handler stays correct
    # because it keeps a set of facts. A handler that overwrote "latest status" on
    # arrival would end in the wrong state; see docs/study/messaging.md.
    inbox, facts = InMemoryInbox(), set()

    def record_fact(transaction, inbound):
        facts.add(inbound.event_type)

    consumer = IdempotentConsumer(inbox, "projection", record_fact)
    stream = [message("a", "OrderAllocated"), message("b", "PickingCompleted"),
              message("c", "OrderPacked")]
    for inbound in [stream[2], stream[0], stream[2], stream[1], stream[0]]:
        consumer.handle(inbound)
    assert facts == {"OrderAllocated", "PickingCompleted", "OrderPacked"}
