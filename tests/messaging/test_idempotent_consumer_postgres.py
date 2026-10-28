"""Inbox row and handler effects commit together, so redelivery cannot double-apply."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from sqlalchemy import text

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.inbound_message import InboundMessage
from messaging.infrastructure.messaging_schema import inbox_messages
from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction

from sqlalchemy import select


def message(message_id="m1"):
    return InboundMessage(message_id, "OrderAllocated", "owner", {"order_id": "o"})


@pytest.fixture
def engine(orders_database):
    with orders_database.begin() as connection:
        connection.execute(text("create table handled (message_id text not null)"))
    return orders_database


def handled(engine):
    with engine.connect() as connection:
        return list(connection.scalars(text("select message_id from handled order by 1")))


def inbox(engine):
    with engine.connect() as connection:
        return list(connection.execute(select(inbox_messages.c.consumer_name, inbox_messages.c.message_id)))


def effect(transaction, inbound):
    transaction.connection.execute(
        text("insert into handled values (:id)"), {"id": inbound.message_id})


def consumer(engine, handler=effect, name="projection"):
    return IdempotentConsumer(lambda: PostgresInboxTransaction(engine), name, handler)


def test_duplicate_and_redelivered_messages_are_processed_once(engine):
    worker = consumer(engine)
    assert worker.handle(message()) is True
    assert worker.handle(message()) is False
    assert worker.handle(message()) is False
    assert handled(engine) == ["m1"]
    assert inbox(engine) == [("projection", "m1")]


def test_handler_failure_leaves_no_inbox_row_and_a_retry_succeeds(engine):
    def failing(transaction, inbound):
        effect(transaction, inbound)
        raise RuntimeError("projection store down")

    with pytest.raises(RuntimeError):
        consumer(engine, failing).handle(message())
    assert (inbox(engine), handled(engine)) == ([], [])
    assert consumer(engine).handle(message()) is True
    assert handled(engine) == ["m1"]


def test_inbox_is_per_consumer(engine):
    assert consumer(engine, name="projection").handle(message()) is True
    assert consumer(engine, name="notifier").handle(message()) is True
    assert handled(engine) == ["m1", "m1"]


def test_out_of_order_delivery_converges_for_an_order_insensitive_handler(engine):
    # Facts are a set, so arrival order cannot change the final state. A handler that
    # overwrote "current status" would NOT be safe: the inbox dedupes, it never orders.
    worker = consumer(engine)
    for message_id in ["m3", "m1", "m3", "m2", "m1"]:
        worker.handle(message(message_id))
    assert handled(engine) == ["m1", "m2", "m3"]


def test_concurrent_duplicate_deliveries_wait_then_become_a_no_op(engine):
    started, release = threading.Event(), threading.Event()
    pids = []

    def slow(transaction, inbound):
        pids.append(transaction.connection.scalar(text("select pg_backend_pid()")))
        effect(transaction, inbound)
        started.set()
        assert release.wait(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(consumer(engine, slow).handle, message())
        assert started.wait(5)
        second = pool.submit(consumer(engine).handle, message())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with engine.connect() as connection:
                if connection.scalar(text("select exists(select 1 from pg_stat_activity "
                                          "where :pid = any(pg_blocking_pids(pid)))"), {"pid": pids[0]}):
                    break
            time.sleep(0.02)
        else:
            pytest.fail("Duplicate delivery never demonstrably waited on the first one")
        assert not second.done()
        release.set()
        assert (first.result(10), second.result(10)) == (True, False)
    assert handled(engine) == ["m1"]
