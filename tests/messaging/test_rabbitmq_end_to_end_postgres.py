"""Outbox row -> relay -> RabbitMQ -> idempotent consumer -> PostgreSQL effect."""
import pytest
from sqlalchemy import text

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.application.outbox_relay import OutboxRelay
from messaging.domain.outbox_status import OutboxStatus
from messaging.infrastructure.outbox_recording import record_outbox_event
from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction
from messaging.infrastructure.postgres_outbox_transaction import PostgresOutboxTransaction
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher

from in_memory_messaging import START, FakeClock, event
from messaging_postgres_support import outbox_rows
from rabbitmq_support import running, wait_until


@pytest.fixture
def engine(orders_database):
    with orders_database.begin() as connection:
        connection.execute(text("create table handled (message_id text not null)"))
    return orders_database


def handled(engine):
    with engine.connect() as connection:
        return list(connection.scalars(text("select message_id from handled order by 1")))


def effect(transaction, inbound):
    transaction.connection.execute(text("insert into handled values (:id)"), {"id": inbound.message_id})


def consumer_runner(engine, broker):
    runner = RabbitMqConsumerRunner(
        broker.url, broker.topology, broker.queue, ["OrderAllocated"],
        IdempotentConsumer(lambda: PostgresInboxTransaction(engine), "projection", effect),
        prefetch=5, max_attempts=3, retry_delay_ms=100)
    runner.declare()
    return runner


def test_outbox_row_reaches_the_consumer_exactly_once_in_effect(engine, broker):
    runner = consumer_runner(engine, broker)
    with engine.begin() as connection:
        record_outbox_event(connection, event("a"), START)
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    relay = OutboxRelay(lambda: PostgresOutboxTransaction(engine), publisher, FakeClock())

    assert relay.run_once().published == 1
    assert outbox_rows(engine, OutboxStatus.PUBLISHED)

    with running(runner) as errors:
        wait_until(lambda: handled(engine), reason="the effect to commit")
    assert errors == []
    assert handled(engine) == ["OrderAllocated:owner:a"]
    publisher.close()


def test_broker_redelivery_plus_inbox_gives_one_effect(engine, broker):
    runner = consumer_runner(engine, broker)
    with engine.begin() as connection:
        record_outbox_event(connection, event("a"), START)
    message = outbox_rows(engine)[0]["message_id"]
    publisher = RabbitMqPublisher(broker.url, broker.topology)
    relay = OutboxRelay(lambda: PostgresOutboxTransaction(engine), publisher, FakeClock())
    relay.run_once()
    # Same message_id published again, as after a relay crash between publish and mark.
    with engine.begin() as connection:
        connection.execute(text("update outbox_messages set status = 'PENDING'"))
    relay.run_once()
    publisher.close()

    with running(runner):
        wait_until(lambda: handled(engine), reason="the effect")
        wait_until(lambda: _inbox_rows(engine) == 1, reason="the inbox row")
    assert handled(engine) == [message]


def _inbox_rows(engine):
    with engine.connect() as connection:
        return connection.scalar(text("select count(*) from inbox_messages"))
