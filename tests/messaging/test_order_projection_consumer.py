"""The projection consumer on real RabbitMQ: its own queue, retry, DLQ, no effect on its neighbours."""
import pika

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.fulfillment_events import order_allocated, order_packed
from messaging.domain.outbox_message import OutboxMessage
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from orders.application.project_order_event import ProjectOrderEvent
from orders.domain import OrderStatus
from orders.infrastructure.dynamodb_order_projection import DynamoDbOrderProjection
from orders.infrastructure.order_projection_worker import (
    CONSUMER_NAME, build_order_projection_runner,
)

from in_memory_messaging import START, InMemoryInbox
from order_projection_support import InMemoryOrderProjection
from rabbitmq_support import queue_depth, running, take, wait_until


def publish(broker, *events):
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    for event in events:
        publisher.publish(OutboxMessage.pending(event, START))
    publisher.close()


def projection_runner(broker, projection, inbox=None, **options):
    runner = build_order_projection_runner(
        inbox or InMemoryInbox(), broker.url, projection,
        topology=broker.topology, queue=broker.queue,
        max_attempts=3, retry_delay_ms=100, **options)
    runner.declare()
    return runner


def test_the_projection_queue_receives_every_order_lifecycle_event_and_projects_them(broker):
    projection = InMemoryOrderProjection()
    runner = projection_runner(broker, projection)
    publish(broker, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]),
            order_packed("owner", "o1", ["p1"]))
    with running(runner) as errors:
        wait_until(lambda: (view := projection.get("owner", "o1")) and view.status == OrderStatus.PACKED,
                   reason="the projection to catch up")
    assert errors == []
    assert projection.get("owner", "o1").warehouse_id == "w1"


def test_a_redelivered_event_is_projected_once(broker):
    projection = InMemoryOrderProjection()
    applied = []
    real_apply = projection.apply
    projection.apply = lambda change: applied.append(change.event_id) or real_apply(change)
    runner = projection_runner(broker, projection, InMemoryInbox())
    event = order_allocated("owner", "o1", "w1", [("l1", "sku", 1)])
    publish(broker, event, event, event)
    with running(runner):
        wait_until(lambda: applied and queue_depth(broker.url, broker.queue) == 0, reason="to drain")
    assert applied == [event.message_id]


def test_a_projection_outage_ends_in_the_dlq_without_losing_the_event(broker):
    projection = InMemoryOrderProjection()
    projection.down = True
    runner = projection_runner(broker, projection)
    event = order_allocated("owner", "o1", "w1", [("l1", "sku", 1)])
    publish(broker, event)
    dlq = broker.topology.dead_letter_queue(broker.queue)
    with running(runner) as errors:
        wait_until(lambda: queue_depth(broker.url, dlq) == 1, reason="the DLQ entry")
    assert errors == []
    properties, body = take(broker.url, dlq)
    assert body["message_id"] == event.message_id
    assert properties.headers["x-attempt"] == 3
    assert "ProjectionUnavailable" in properties.headers["x-last-error"]


def test_an_unreachable_dynamodb_endpoint_takes_the_same_retry_path(broker):
    # The real adapter against a closed port, not a double that raises on cue.
    runner = projection_runner(broker, DynamoDbOrderProjection("http://127.0.0.1:1", timeout_seconds=0.2))
    publish(broker, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]))
    with running(runner):
        wait_until(lambda: queue_depth(broker.url, broker.topology.dead_letter_queue(broker.queue)) == 1,
                   reason="the DLQ entry")


def test_an_outage_that_heals_within_the_retry_budget_loses_nothing(broker):
    projection = InMemoryOrderProjection()
    projection.down = True
    runner = projection_runner(broker, projection)
    publish(broker, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]))
    with running(runner):
        wait_until(lambda: queue_depth(broker.url, broker.topology.retry_queue(broker.queue)) == 1
                   or queue_depth(broker.url, broker.queue) == 1, reason="a first failed attempt")
        projection.down = False
        wait_until(lambda: projection.get("owner", "o1"), reason="the retry to succeed")
    assert queue_depth(broker.url, broker.topology.dead_letter_queue(broker.queue)) == 0


def test_a_failing_projection_does_not_block_another_consumer_of_the_same_event(broker):
    projection = InMemoryOrderProjection()
    projection.down = True
    runner = projection_runner(broker, projection)
    # A second, independent consumer bound to the same exchange with its own queue.
    other_queue, other_seen = broker.queue + ".other", []
    other = RabbitMqConsumerRunner(
        broker.url, broker.topology, other_queue, ["OrderAllocated"],
        IdempotentConsumer(InMemoryInbox(), "other", lambda tx, message: other_seen.append(message.message_id)),
        max_attempts=3, retry_delay_ms=100)
    other.declare()
    event = order_allocated("owner", "o1", "w1", [("l1", "sku", 1)])
    publish(broker, event)
    try:
        with running(runner), running(other):
            wait_until(lambda: other_seen == [event.message_id], reason="the healthy consumer")
            wait_until(lambda: queue_depth(
                broker.url, broker.topology.dead_letter_queue(broker.queue)) == 1, reason="the DLQ entry")
    finally:
        with pika.BlockingConnection(pika.URLParameters(broker.url)) as connection:
            channel = connection.channel()
            for name in (other_queue, broker.topology.retry_queue(other_queue),
                         broker.topology.dead_letter_queue(other_queue)):
                channel.queue_delete(name)
