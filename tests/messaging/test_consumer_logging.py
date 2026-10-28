"""Retry and dead-letter decisions are logged with the ids needed to find the message again.

No broker: the runner's per-delivery step is driven with a recording channel.
"""
import json
import logging
from types import SimpleNamespace

from log_capture_support import capture_logs
from messaging.domain.inbound_message import InboundMessage
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology

EVENT_ID = "OrderAllocated:owner:o1"
BODY = json.dumps({"message_id": EVENT_ID, "event_type": "OrderAllocated", "client_id": "owner",
                   "aggregate_type": "order", "aggregate_id": "o1",
                   "payload": {"ssn": "123-45-6789"}}).encode()


class RecordingChannel:
    def __init__(self):
        self.published, self.acked = [], []

    def basic_publish(self, exchange, queue, body, properties, mandatory):
        self.published.append(queue)

    def basic_ack(self, tag):
        self.acked.append(tag)


class Consumer:
    def __init__(self, error=None):
        self.error = error

    def handle(self, message: InboundMessage):
        if self.error:
            raise self.error
        return True


def deliver(consumer, body=BODY, attempt=None, max_attempts=3):
    runner = RabbitMqConsumerRunner(
        "amqp://lab:lab@127.0.0.1:1/", RabbitMqTopology("x.events"), "q.projection", ["OrderAllocated"],
        consumer, max_attempts=max_attempts)
    headers = {} if attempt is None else {"x-attempt": attempt}
    properties = SimpleNamespace(headers=headers, message_id=EVENT_ID, content_type="application/json")
    channel = RecordingChannel()
    with capture_logs() as logs:
        runner._process(channel, 1, properties, body)
    return logs, channel


def test_a_failure_that_will_be_retried_logs_a_warning_with_the_event_ids():
    logs, channel = deliver(Consumer(RuntimeError("projection store down")))
    (line,) = logs.from_logger("messaging.consumer")
    assert line["level"] == "WARNING" and line["decision"] == "retry" and line["attempt"] == 1
    assert (line["event_id"], line["event_type"], line["queue"]) == (EVENT_ID, "OrderAllocated", "q.projection")
    assert "RuntimeError: projection store down" in line["exception"]
    assert len(channel.published) == 1 and channel.acked == [1]


def test_the_last_attempt_logs_an_error_saying_the_message_was_dead_lettered():
    logs, _ = deliver(Consumer(RuntimeError("poisoned")), attempt=2)
    (line,) = logs.from_logger("messaging.consumer")
    assert line["level"] == "ERROR" and line["decision"] == "dead_letter" and line["attempt"] == 3
    assert line["event_id"] == EVENT_ID


def test_an_undecodable_body_is_logged_as_dead_lettered_with_the_broker_message_id():
    logs, channel = deliver(Consumer(), body=b"not json")
    (line,) = logs.from_logger("messaging.consumer")
    assert line["level"] == "ERROR" and line["decision"] == "dead_letter"
    assert line["event_id"] == EVENT_ID and "event_type" not in line
    assert len(channel.published) == 1 and channel.acked == [1]


def test_a_successful_delivery_logs_no_warning_or_error():
    logs, channel = deliver(Consumer())
    assert [line for line in logs.lines if line["level"] in ("WARNING", "ERROR")] == []
    assert channel.published == [] and channel.acked == [1]


def test_payloads_are_never_logged():
    logs, _ = deliver(Consumer(RuntimeError("down")))
    assert "123-45-6789" not in json.dumps(logs.lines)


def test_ids_do_not_leak_into_later_log_lines():
    logs, _ = deliver(Consumer(RuntimeError("down")))
    with capture_logs() as later:
        logging.getLogger("lab.after").info("idle")
    assert "event_id" not in later.lines[0] and "queue" not in later.lines[0]
