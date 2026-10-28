"""PostgreSQL outbox -> relay -> RabbitMQ -> projection consumer -> DynamoDB Local -> rebuild."""
from uuid import uuid4

import pytest

from messaging.application.outbox_relay import OutboxRelay
from messaging.domain.fulfillment_events import (
    order_allocated, order_cancelled, order_packed, order_shipped, picking_completed,
)
from messaging.infrastructure.outbox_recording import record_outbox_event
from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction
from messaging.infrastructure.postgres_outbox_transaction import PostgresOutboxTransaction
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher
from orders.application.rebuild_order_projection import RebuildOrderProjection
from orders.domain import OrderStatus
from orders.infrastructure.dynamodb_order_projection import DynamoDbOrderProjection
from orders.infrastructure.order_projection_worker import build_order_projection_runner
from orders.infrastructure.postgres_outbox_order_events import PostgresOutboxOrderEvents

from in_memory_messaging import START, FakeClock
from rabbitmq_support import queue_depth, running, wait_until


@pytest.fixture
def projection(dynamodb_url):
    real = DynamoDbOrderProjection(dynamodb_url, table_name=f"lab_test_{uuid4().hex}")
    real.install()
    try:
        yield real
    finally:
        real.drop()


def test_events_reach_the_projection_and_a_lost_projection_is_rebuilt(orders_database, broker, projection):
    runner = build_order_projection_runner(
        lambda: PostgresInboxTransaction(orders_database), broker.url, projection,
        topology=broker.topology, queue=broker.queue, max_attempts=3, retry_delay_ms=100)
    runner.declare()
    history = [
        order_allocated("owner", "o1", "w1", [("l1", "sku", 2)]),
        order_allocated("owner", "o2", "w1", [("l1", "sku", 1)]),
        order_cancelled("owner", "o2"),
        picking_completed("owner", "o1"),
        order_packed("owner", "o1", ["p1", "p2"]),
        order_shipped("owner", "o1", "attempt", "trk-1", ["p1", "p2"]),
    ]
    with orders_database.begin() as connection:
        for event in history:
            record_outbox_event(connection, event, START)
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    relay = OutboxRelay(lambda: PostgresOutboxTransaction(orders_database), publisher, FakeClock())
    assert relay.run_once().published == len(history)
    publisher.close()

    def caught_up():
        shipped, cancelled = projection.get("owner", "o1"), projection.get("owner", "o2")
        return (shipped and shipped.status == OrderStatus.SHIPPED
                and cancelled and cancelled.status == OrderStatus.CANCELLED)

    with running(runner) as errors:
        wait_until(caught_up, timeout=15, reason="the projection to catch up")
        wait_until(lambda: queue_depth(broker.url, broker.queue) == 0, reason="the queue to drain")
    assert errors == []
    live = projection.list_for_client("owner")
    assert [(v.order_id, v.status) for v in live] == [
        ("o1", OrderStatus.SHIPPED), ("o2", OrderStatus.CANCELLED)]

    projection.drop()
    RebuildOrderProjection(projection, PostgresOutboxOrderEvents(orders_database)).run()
    assert projection.list_for_client("owner") == live
