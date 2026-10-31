"""Consumer runner behaviour that needs no broker: a scripted fake channel."""
from types import SimpleNamespace

import pika
import pytest

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.infrastructure import rabbitmq_consumer_runner
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from messaging.infrastructure.rabbitmq_message import encode
from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology

from in_memory_messaging import InMemoryInbox, pending

QUEUE = "fake.queue"
TOPOLOGY = RabbitMqTopology("fake.events")
DLQ = TOPOLOGY.dead_letter_queue(QUEUE)
RETRY = TOPOLOGY.retry_queue(QUEUE)


class FakeChannel:
    def __init__(self, deliveries, publish_error=None):
        self._deliveries = deliveries
        self._publish_error = publish_error
        self.log = []
        self.cancelled = False

    def confirm_delivery(self):
        pass

    def basic_qos(self, prefetch_count):
        pass

    def consume(self, queue, inactivity_timeout):
        for tag, headers, body in self._deliveries:
            self.log.append(("deliver", tag))
            properties = SimpleNamespace(headers=headers, message_id=f"m{tag}", content_type=None)
            yield SimpleNamespace(delivery_tag=tag), properties, body
        while True:
            yield None, None, None

    def cancel(self):
        self.cancelled = True

    def basic_ack(self, tag):
        self.log.append(("ack", tag))

    def basic_publish(self, exchange, queue, body, properties, mandatory):
        if self._publish_error:
            raise self._publish_error
        self.log.append(("publish", queue, properties.headers["x-attempt"]))


class FakeConnection:
    is_open = True

    def __init__(self, channel):
        self._channel = channel

    def channel(self):
        return self._channel

    def close(self):
        self.is_open = False


def make_runner(monkeypatch, channel, handler, *, max_attempts=3):
    monkeypatch.setattr(pika, "BlockingConnection", lambda parameters: FakeConnection(channel))
    runner = RabbitMqConsumerRunner(
        "amqp://guest:guest@localhost:5672/%2F", TOPOLOGY, QUEUE, ["OrderAllocated"],
        IdempotentConsumer(InMemoryInbox(), "projection", handler), max_attempts=max_attempts)
    monkeypatch.setattr(runner, "_declare", lambda channel: None)
    return runner


def body():
    return encode(pending("o1"))


def failing(transaction, message):
    raise RuntimeError("boom")


@pytest.mark.parametrize("bad", ["2", None, -1, True, 1.0], ids=repr)
def test_invalid_attempt_header_is_dead_lettered_before_the_ack_without_running_the_handler(
        monkeypatch, bad):
    calls = []
    channel = FakeChannel([(1, {rabbitmq_consumer_runner.ATTEMPT_HEADER: bad}, body())])
    runner = make_runner(monkeypatch, channel, lambda tx, message: calls.append(message))
    runner.run(should_stop=lambda: True)
    assert calls == []
    assert channel.log == [("deliver", 1), ("publish", DLQ, 0), ("ack", 1)]


def test_failed_dlq_publish_for_invalid_header_leaves_the_delivery_unacked(monkeypatch):
    channel = FakeChannel([(1, {"x-attempt": "2"}, body())], publish_error=RuntimeError("nacked"))
    runner = make_runner(monkeypatch, channel, failing)
    with pytest.raises(RuntimeError, match="nacked"):
        runner.run(should_stop=lambda: True)
    assert ("ack", 1) not in channel.log


def test_valid_attempt_header_is_incremented_and_retried(monkeypatch):
    channel = FakeChannel([(1, {"x-attempt": 1}, body())])
    runner = make_runner(monkeypatch, channel, failing)
    runner.run(should_stop=lambda: True)
    assert channel.log == [("deliver", 1), ("publish", RETRY, 2), ("ack", 1)]


def test_stop_requested_during_a_handler_is_honoured_before_the_next_delivery(monkeypatch):
    stop, handled = [], []

    def handler(transaction, message):
        handled.append(message.message_id)
        stop.append(True)

    channel = FakeChannel([(1, None, body()), (2, None, body()), (3, None, body())])
    runner = make_runner(monkeypatch, channel, handler)
    runner.run(should_stop=lambda: bool(stop))
    assert len(handled) == 1
    assert channel.log == [("deliver", 1), ("ack", 1)]
    assert channel.cancelled  # prefetched deliveries 2 and 3 go back to the queue


def test_idle_queue_still_stops_on_the_flag(monkeypatch):
    channel = FakeChannel([])
    runner = make_runner(monkeypatch, channel, failing)
    runner.run(should_stop=lambda: True)
    assert channel.log == []
