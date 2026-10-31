"""Publishing to RabbitMQ: confirms, mandatory routing, and every failure as PublishFailed."""
from datetime import timedelta

import pika
import pytest

from messaging.application.outbox_relay import OutboxRelay
from messaging.application.publish_failed import PublishFailed
from messaging.domain.retry_policy import RetryPolicy
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher
from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology

from in_memory_messaging import START, FakeClock, InMemoryOutbox, pending
from rabbitmq_support import queue_depth, raw_channel, take

NOTHING_LISTENING = "amqp://lab:lab@127.0.0.1:1/"


def bind_queue(broker, routing_key="OrderAllocated", **arguments):
    with raw_channel(broker.url) as channel:
        broker.topology.declare_exchange(channel)
        channel.queue_declare(broker.queue, durable=True, arguments=arguments or None)
        channel.queue_bind(broker.queue, broker.topology.exchange, routing_key)


def test_published_message_is_persistent_and_carries_the_outbox_message_id(broker):
    bind_queue(broker)
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    message = pending("o1")
    publisher.publish(message)
    publisher.close()
    properties, body = take(broker.url, broker.queue)
    assert properties.message_id == message.message_id
    assert properties.delivery_mode == pika.DeliveryMode.Persistent.value
    assert properties.headers["event_type"] == "OrderAllocated"
    assert body["message_id"] == message.message_id
    assert body["payload"] == {"order_id": "o1"}


def test_exchange_is_a_durable_topic_and_declaring_twice_is_harmless(broker):
    bind_queue(broker)
    RabbitMqPublisher(broker.url, broker.topology).close()
    with raw_channel(broker.url) as channel:
        broker.topology.declare_exchange(channel)
        broker.topology.declare_exchange(channel)
        # passive declare of a mismatching type/durability would raise; matching succeeds
        channel.exchange_declare(broker.topology.exchange, exchange_type="topic",
                                 durable=True, passive=True)


def test_unroutable_message_fails_instead_of_being_silently_dropped(broker):
    bind_queue(broker, routing_key="SomethingElse")
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    with pytest.raises(PublishFailed, match="unroutable|returned|route"):
        publisher.publish(pending("o1"))
    publisher.close()
    assert queue_depth(broker.url, broker.queue) == 0


def test_broker_nack_becomes_publish_failed(broker):
    # A full queue with reject-publish makes the broker nack the confirm.
    bind_queue(broker, **{"x-max-length": 1, "x-overflow": "reject-publish"})
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    publisher.publish(pending("o1"))
    with pytest.raises(PublishFailed, match="nack"):
        publisher.publish(pending("o2"))
    publisher.close()
    assert queue_depth(broker.url, broker.queue) == 1


def test_publisher_reconnects_after_the_connection_is_lost(broker):
    bind_queue(broker)
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    publisher.publish(pending("o1"))
    publisher._connection.close()  # a dropped connection the client already noticed
    publisher.publish(pending("o2"))
    publisher.close()
    assert queue_depth(broker.url, broker.queue) == 2


def test_unreachable_broker_is_publish_failed_not_a_pika_error():
    publisher = RabbitMqPublisher(NOTHING_LISTENING, RabbitMqTopology("unused"), timeout_seconds=1)
    with pytest.raises(PublishFailed):
        publisher.publish(pending("o1"))


def test_relay_keeps_the_message_and_backs_off_while_the_broker_is_down():
    outbox = InMemoryOutbox(pending("o1"))
    clock = FakeClock()
    policy = RetryPolicy(max_attempts=5, base_delay=timedelta(seconds=10))
    publisher = RabbitMqPublisher(NOTHING_LISTENING, RabbitMqTopology("unused"), timeout_seconds=1)
    relay = OutboxRelay(outbox, publisher, clock, policy)

    assert relay.run_once().retried == 1
    stored = outbox.get(pending("o1").message_id)
    assert (stored.status.value, stored.attempt_count) == ("PENDING", 1)
    assert stored.next_attempt_at == START + timedelta(seconds=10)
    assert stored.last_error
