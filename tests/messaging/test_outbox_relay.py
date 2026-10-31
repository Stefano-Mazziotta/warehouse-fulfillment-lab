from datetime import timedelta

import pytest

from messaging.application.outbox_relay import OutboxRelay
from messaging.domain.outbox_status import OutboxStatus
from messaging.domain.retry_policy import RetryPolicy
from messaging.infrastructure.in_memory_publisher import InMemoryPublisher

from in_memory_messaging import START, FakeClock, InMemoryOutbox, pending

POLICY = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=10), max_delay=timedelta(minutes=1))


def relay(outbox, publisher, clock=None, **options):
    return OutboxRelay(outbox, publisher, clock or FakeClock(), POLICY, **options)


def test_publishes_due_messages_in_creation_order_and_marks_them():
    first, second = pending("a"), pending("b", created_at=START + timedelta(seconds=1))
    outbox, publisher = InMemoryOutbox(second, first), InMemoryPublisher()
    result = relay(outbox, publisher, FakeClock(START + timedelta(seconds=5))).run_once()
    assert [m.message_id for m in publisher.published] == [first.message_id, second.message_id]
    assert (result.published, result.retried, result.dead) == (2, 0, 0)
    assert {m.status for m in outbox.rows.values()} == {OutboxStatus.PUBLISHED}


def test_future_and_terminal_messages_are_left_alone():
    future = pending("future", next_attempt_at=START + timedelta(hours=1))
    done, dead = pending("done").published(), pending("dead", status=OutboxStatus.DEAD)
    outbox, publisher = InMemoryOutbox(future, done, dead), InMemoryPublisher()
    assert relay(outbox, publisher).run_once().published == 0
    assert publisher.published == []


def test_batch_size_bounds_one_run():
    outbox = InMemoryOutbox(*(pending(str(i)) for i in range(5)))
    publisher = InMemoryPublisher()
    assert relay(outbox, publisher, batch_size=2).run_once().published == 2
    assert len(publisher.published) == 2


def test_failure_backs_off_exponentially_and_is_not_retried_early():
    clock, outbox, publisher = FakeClock(), InMemoryOutbox(pending()), InMemoryPublisher()
    publisher.fail_next(2, "broker down")
    worker = relay(outbox, publisher, clock)
    assert worker.run_once().retried == 1
    message = outbox.get("OrderAllocated:owner:order")
    assert (message.attempt_count, message.next_attempt_at) == (1, START + timedelta(seconds=10))
    clock.advance(seconds=9)
    assert worker.run_once().retried == 0
    clock.advance(seconds=1)
    assert worker.run_once().retried == 1
    assert outbox.get(message.message_id).next_attempt_at == clock() + timedelta(seconds=20)
    clock.advance(seconds=20)
    assert worker.run_once().published == 1
    assert outbox.get(message.message_id).status == OutboxStatus.PUBLISHED


def test_message_dies_after_the_attempt_limit_and_is_never_retried():
    clock, outbox, publisher = FakeClock(), InMemoryOutbox(pending()), InMemoryPublisher()
    publisher.fail_next(99, "poison")
    worker = relay(outbox, publisher, clock)
    results = []
    for _ in range(4):
        results.append(worker.run_once())
        clock.advance(minutes=5)
    assert [(r.retried, r.dead) for r in results] == [(1, 0), (1, 0), (0, 1), (0, 0)]
    message = outbox.get("OrderAllocated:owner:order")
    assert (message.status, message.attempt_count, message.last_error) == (
        OutboxStatus.DEAD, 3, "poison")
    assert publisher.attempts == 3


def test_one_poison_message_does_not_block_the_rest_of_the_batch():
    outbox = InMemoryOutbox(pending("bad"), pending("good", created_at=START + timedelta(seconds=1)))
    publisher = InMemoryPublisher()
    publisher.fail_when(lambda m: m.aggregate_id == "bad")
    result = relay(outbox, publisher, FakeClock(START + timedelta(seconds=2))).run_once()
    assert (result.published, result.retried) == (1, 1)


def test_crash_between_publish_and_mark_redelivers_the_message():
    # At-least-once: the broker has the message, the database does not know yet.
    outbox, publisher = InMemoryOutbox(pending()), InMemoryPublisher()
    outbox.fail_on_save = RuntimeError("connection lost before commit")
    with pytest.raises(RuntimeError):
        relay(outbox, publisher).run_once()
    assert len(publisher.published) == 1
    assert outbox.get("OrderAllocated:owner:order").status == OutboxStatus.PENDING
    outbox.fail_on_save = None
    assert relay(outbox, publisher).run_once().published == 1
    assert [m.message_id for m in publisher.published] == ["OrderAllocated:owner:order"] * 2
