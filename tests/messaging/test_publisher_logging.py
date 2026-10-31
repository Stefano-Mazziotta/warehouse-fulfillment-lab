"""A failed publish leaves a log line naming the event, never the broker credentials."""
import json

import pytest

from log_capture_support import capture_logs
from messaging.application.publish_failed import PublishFailed
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher

from in_memory_messaging import pending


def test_publish_failure_is_logged_with_the_event_ids_and_no_credentials():
    publisher = RabbitMqPublisher("amqp://lab:s3cret@127.0.0.1:1/")  # nothing listens on port 1
    message = pending("o1")
    with capture_logs() as logs, pytest.raises(PublishFailed):
        publisher.publish(message)
    (line,) = logs.from_logger("messaging.publisher")
    assert line["level"] == "WARNING"
    assert line["event_id"] == message.message_id and line["event_type"] == "OrderAllocated"
    assert "s3cret" not in json.dumps(logs.lines)


def test_an_unroutable_message_is_logged_with_its_reason(broker):
    # The exchange exists but no queue is bound for the event type: the mandatory flag reports it.
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    message = pending("o1")
    with capture_logs() as logs, pytest.raises(PublishFailed):
        publisher.publish(message)
    publisher.close()
    (line,) = logs.from_logger("messaging.publisher")
    assert line["reason"] == "unroutable" and line["event_id"] == message.message_id
