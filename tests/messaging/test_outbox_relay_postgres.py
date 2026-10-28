"""The relay against real PostgreSQL: claiming, backoff persistence and redelivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time

import pytest
from sqlalchemy import text

from messaging.application.outbox_relay import OutboxRelay
from messaging.domain.outbox_status import OutboxStatus
from messaging.domain.retry_policy import RetryPolicy
from messaging.infrastructure.in_memory_publisher import InMemoryPublisher
from messaging.infrastructure.outbox_recording import record_outbox_event
from messaging.infrastructure.postgres_outbox_transaction import PostgresOutboxTransaction

from in_memory_messaging import START, FakeClock, event
from messaging_postgres_support import outbox_rows

POLICY = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=10), max_delay=timedelta(minutes=1))


def seed_events(engine, *order_ids, at=START):
    with engine.begin() as connection:
        for order_id in order_ids:
            record_outbox_event(connection, event(order_id), at)


def relay(engine, publisher, clock=None, transaction=PostgresOutboxTransaction, **options):
    return OutboxRelay(lambda: transaction(engine), publisher, clock or FakeClock(), POLICY, **options)


def wait_for_block(engine, blocker):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.scalar(text("select exists(select 1 from pg_stat_activity "
                                      "where :pid = any(pg_blocking_pids(pid)))"), {"pid": blocker}):
                return
        time.sleep(0.02)
    pytest.fail("Plain FOR UPDATE never demonstrably waited on the claimed row")


class HoldingPublisher(InMemoryPublisher):
    """Parks inside publish() so the claim lock is provably held."""

    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def publish(self, message):
        self.entered.set()
        assert self.release.wait(10)
        super().publish(message)


class PidRecordingTransaction(PostgresOutboxTransaction):
    pids = []

    def __enter__(self):
        super().__enter__()
        self.pids.append(self._connection().scalar(text("select pg_backend_pid()")))
        return self


def test_relay_publishes_and_marks_published(orders_database):
    engine = orders_database
    seed_events(engine, "a", "b")
    publisher = InMemoryPublisher()
    assert relay(engine, publisher).run_once().published == 2
    assert {r["status"] for r in outbox_rows(engine)} == {"PUBLISHED"}
    assert relay(engine, publisher).run_once().published == 0


def test_concurrent_relays_never_double_claim(orders_database):
    engine = orders_database
    seed_events(engine, "a", "b")
    PidRecordingTransaction.pids = []
    holder, other = HoldingPublisher(), InMemoryPublisher()
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(
            relay(engine, holder, transaction=PidRecordingTransaction, batch_size=1).run_once)
        assert holder.entered.wait(5)
        claimed = outbox_rows(engine, OutboxStatus.PENDING)
        assert len(claimed) == 2  # the claim is uncommitted: nothing is marked yet

        # A plain FOR UPDATE on the held row DOES wait: the lock is real.
        def plain_lock():
            with engine.begin() as connection:
                connection.execute(text(
                    "select 1 from outbox_messages where message_id = :id for update"),
                    {"id": claimed[0]["message_id"]})
        probe = pool.submit(plain_lock)
        wait_for_block(engine, PidRecordingTransaction.pids[0])

        # SKIP LOCKED does not wait: the second relay moves on to the free row.
        started = time.monotonic()
        second = relay(engine, other, batch_size=10).run_once()
        assert time.monotonic() - started < 2
        assert (second.published, [m.aggregate_id for m in other.published]) == (1, ["b"])

        holder.release.set()
        assert first.result(10).published == 1
        probe.result(10)
    assert [m.aggregate_id for m in holder.published] == ["a"]
    assert {r["status"] for r in outbox_rows(engine)} == {"PUBLISHED"}


def test_two_relays_over_many_rows_publish_each_message_exactly_once(orders_database):
    engine = orders_database
    seed_events(engine, *(f"o{i}" for i in range(20)))
    publishers = [InMemoryPublisher(), InMemoryPublisher()]
    barrier = threading.Barrier(2)

    def drain(publisher):
        barrier.wait()
        worker = relay(engine, publisher, batch_size=3)
        while worker.run_once().published:
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(drain, p) for p in publishers]:
            future.result(20)
    delivered = [m.message_id for p in publishers for m in p.published]
    assert sorted(delivered) == sorted(r["message_id"] for r in outbox_rows(engine))
    assert len(delivered) == len(set(delivered)) == 20


def test_backoff_and_dead_state_survive_in_the_database(orders_database):
    engine = orders_database
    seed_events(engine, "a")
    clock, publisher = FakeClock(), InMemoryPublisher()
    publisher.fail_next(99, "broker down")
    worker = relay(engine, publisher, clock)
    worker.run_once()
    (row,) = outbox_rows(engine)
    assert (row["status"], row["attempt_count"], row["last_error"], row["next_attempt_at"]) == (
        "PENDING", 1, "broker down", START + timedelta(seconds=10))
    assert worker.run_once().retried == 0  # not due yet: no publish attempt
    assert publisher.attempts == 1
    clock.advance(seconds=10)
    worker.run_once()
    assert outbox_rows(engine)[0]["next_attempt_at"] == clock() + timedelta(seconds=20)
    clock.advance(seconds=20)
    assert worker.run_once().dead == 1
    (row,) = outbox_rows(engine)
    assert (row["status"], row["attempt_count"]) == ("DEAD", 3)
    clock.advance(hours=1)
    assert worker.run_once().published == 0
    assert publisher.attempts == 3


def test_crash_between_publish_and_mark_redelivers(orders_database):
    engine = orders_database
    seed_events(engine, "a")
    publisher = InMemoryPublisher()

    class CrashesOnMark(PostgresOutboxTransaction):
        def save(self, message):
            raise ConnectionError("lost the database after the broker accepted the message")

    with pytest.raises(ConnectionError):
        relay(engine, publisher, transaction=CrashesOnMark).run_once()
    assert len(publisher.published) == 1
    assert outbox_rows(engine)[0]["status"] == "PENDING"

    assert relay(engine, publisher).run_once().published == 1
    assert [m.message_id for m in publisher.published] == ["OrderAllocated:owner:a"] * 2
    assert outbox_rows(engine)[0]["status"] == "PUBLISHED"
