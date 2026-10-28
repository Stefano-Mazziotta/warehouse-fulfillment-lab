"""Consuming from RabbitMQ: ack after commit, bounded retry, dead-letter queue."""
import json

import pika

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher

from in_memory_messaging import InMemoryInbox, pending
from rabbitmq_support import queue_depth, raw_channel, running, take, wait_until


class SimulatedCrash(BaseException):
    """Not an Exception: the runner must not treat it as a handler failure."""


def build(broker, handler, inbox=None, *, max_attempts=3, wrap=lambda consumer: consumer):
    inbox = inbox or InMemoryInbox()
    consumer = wrap(IdempotentConsumer(inbox, "projection", handler))
    runner = RabbitMqConsumerRunner(
        broker.url, broker.topology, broker.queue, ["OrderAllocated"], consumer,
        prefetch=5, max_attempts=max_attempts, retry_delay_ms=100)
    runner.declare()
    return runner, inbox


def send(broker, *order_ids):
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    for order_id in order_ids:
        publisher.publish(pending(order_id))
    publisher.close()


def recording(calls):
    def handler(transaction, message):
        calls.append(message.message_id)
        transaction.effects.append(message.message_id)
    return handler


def test_message_is_consumed_once_and_acknowledged(broker):
    calls = []
    runner, inbox = build(broker, recording(calls))
    send(broker, "o1")
    with running(runner) as errors:
        wait_until(lambda: calls, reason="the handler to run")
    assert errors == []
    assert inbox.effects == ["OrderAllocated:owner:o1"]
    assert queue_depth(broker.url, broker.queue) == 0


def test_duplicate_delivery_of_the_same_message_id_has_one_effect(broker):
    calls = []
    runner, inbox = build(broker, recording(calls))
    send(broker, "o1", "o1", "o1")
    with running(runner):
        wait_until(lambda: queue_depth(broker.url, broker.queue) == 0 and calls,
                   reason="duplicates to drain")
        # An observable no-op: the same id is processed by the inbox, not the handler
        wait_until(lambda: len(inbox.seen) == 1, reason="the inbox row")
    assert calls == ["OrderAllocated:owner:o1"]
    assert inbox.effects == ["OrderAllocated:owner:o1"]
    # Anything left unacked would have been requeued when the runner disconnected.
    assert queue_depth(broker.url, broker.queue) == 0


def test_failing_handler_is_retried_with_a_delay_and_then_succeeds(broker):
    calls = []

    def flaky(transaction, message):
        calls.append(message.message_id)
        if len(calls) < 3:
            raise RuntimeError("projection store down")
        transaction.effects.append(message.message_id)

    runner, inbox = build(broker, flaky)
    send(broker, "o1")
    with running(runner) as errors:
        wait_until(lambda: inbox.effects, reason="the third attempt to succeed")
    assert errors == []
    assert len(calls) == 3 and inbox.effects == ["OrderAllocated:owner:o1"]
    assert queue_depth(broker.url, broker.topology.dead_letter_queue(broker.queue)) == 0


def test_message_goes_to_the_dead_letter_queue_after_max_attempts(broker):
    calls = []

    def always_fails(transaction, message):
        calls.append(message.message_id)
        raise RuntimeError("poisoned projection")

    runner, inbox = build(broker, always_fails, max_attempts=3)
    send(broker, "o1")
    dlq = broker.topology.dead_letter_queue(broker.queue)
    with running(runner) as errors:
        wait_until(lambda: queue_depth(broker.url, dlq) == 1, reason="the DLQ entry")
    assert errors == []
    assert len(calls) == 3
    properties, body = take(broker.url, dlq)
    assert properties.headers["x-attempt"] == 3
    assert "poisoned projection" in properties.headers["x-last-error"]
    assert properties.message_id == "OrderAllocated:owner:o1" == body["message_id"]
    assert inbox.effects == []
    assert queue_depth(broker.url, broker.queue) == 0
    assert queue_depth(broker.url, broker.topology.retry_queue(broker.queue)) == 0


def test_undecodable_message_is_dead_lettered_without_retrying(broker):
    calls = []
    runner, _ = build(broker, recording(calls))
    with raw_channel(broker.url) as channel:
        channel.basic_publish(broker.topology.exchange, "OrderAllocated", b"not json")
    dlq = broker.topology.dead_letter_queue(broker.queue)
    with running(runner):
        wait_until(lambda: queue_depth(broker.url, dlq) == 1, reason="the DLQ entry")
    assert calls == []


def test_crash_after_commit_but_before_ack_is_redelivered_and_deduplicated(broker):
    calls, results = [], []

    class CrashAfterCommit:
        def __init__(self, consumer):
            self._consumer = consumer
            self.crash = True

        def handle(self, message):
            handled = self._consumer.handle(message)  # transaction committed here
            results.append(handled)
            if self.crash:
                self.crash = False
                raise SimulatedCrash("process died before basic_ack")
            return handled

    crasher = {}

    def wrap(consumer):
        crasher["consumer"] = CrashAfterCommit(consumer)
        return crasher["consumer"]

    runner, inbox = build(broker, recording(calls), wrap=wrap)
    send(broker, "o1")
    with running(runner) as errors:
        wait_until(lambda: errors, reason="the simulated crash")
    assert isinstance(errors[0], SimulatedCrash)
    assert inbox.effects == ["OrderAllocated:owner:o1"]
    # The unacked delivery went back to the queue when the connection died.
    wait_until(lambda: queue_depth(broker.url, broker.queue) == 1, reason="redelivery")

    with running(runner) as errors:
        wait_until(lambda: len(results) == 2, reason="the redelivery to be handled")
    assert errors == []
    assert results == [True, False]
    assert calls == ["OrderAllocated:owner:o1"]
    assert queue_depth(broker.url, broker.queue) == 0


def test_prefetch_bounds_unacknowledged_messages(broker):
    entered, release = [], []

    def blocking(transaction, message):
        entered.append(message.message_id)
        wait_until(lambda: release, reason="release")

    inbox = InMemoryInbox()
    runner = RabbitMqConsumerRunner(
        broker.url, broker.topology, broker.queue, ["OrderAllocated"],
        IdempotentConsumer(inbox, "projection", blocking), prefetch=1, max_attempts=3,
        retry_delay_ms=100)
    runner.declare()
    send(broker, "o1", "o2", "o3")
    with running(runner):
        wait_until(lambda: entered, reason="first delivery")
        # One in flight, two still ready on the broker: nothing was pushed past prefetch.
        wait_until(lambda: queue_depth(broker.url, broker.queue) == 2, reason="bounded prefetch")
        release.append(True)
        wait_until(lambda: queue_depth(broker.url, broker.queue) == 0 and len(entered) == 3,
                   reason="the queue to drain")


def test_declaring_the_consumer_topology_twice_is_harmless(broker):
    runner, _ = build(broker, recording([]))
    runner.declare()
    with raw_channel(broker.url) as channel:
        for queue in (broker.queue, broker.topology.retry_queue(broker.queue),
                      broker.topology.dead_letter_queue(broker.queue)):
            assert channel.queue_declare(queue, passive=True).method.queue == queue
