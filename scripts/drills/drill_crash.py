"""Drill 5: a consumer dies after commit but before ack; a relay dies mid-batch."""
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import pika

from demo_format import render_table
from demo_gateways import child_env
from demo_processes import wait_until
from drill_context import DrillContext
from drill_core import Check, Drill, DrillFailure, Explanation, Outcome
from drill_effects import runner_for, stock_receipt_consumer
from messaging.application.outbox_relay import OutboxRelay
from messaging.domain.integration_event import IntegrationEvent
from messaging.infrastructure.outbox_recording import record_outbox_event
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher
from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology
from outbox_relay_worker import ClientScopedOutbox

CHILD = Path(__file__).with_name("drill_child.py")
CHILD_TIMEOUT_SECONDS = 60


class CountingConsumer:
    def __init__(self, real) -> None:
        self._real = real
        self.results: list[bool] = []

    def handle(self, message) -> bool:
        applied = self._real.handle(message)
        self.results.append(applied)
        return applied


def queue_counts(amqp_url: str, queue: str) -> tuple[int, int]:
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    try:
        method = connection.channel().queue_declare(queue, passive=True).method
        return method.message_count, method.consumer_count
    finally:
        connection.close()


def delete_queues(amqp_url: str, queue: str) -> None:
    topology = RabbitMqTopology()
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    try:
        channel = connection.channel()
        for name in (queue, topology.retry_queue(queue), topology.dead_letter_queue(queue)):
            channel.queue_delete(name)
    finally:
        connection.close()


def act(context: DrillContext) -> Outcome:
    ids, engine, say, truth, settings = context.ids, context.engine, context.say, context.truth, context.settings
    amqp = settings.amqp_url
    truth.seed_stock(ids, 0)
    consumer = stock_receipt_consumer(engine, ids.consumer_name)
    runner_for(amqp, ids.queue, ids.event_type, consumer).declare()
    context.defer(lambda: delete_queues(amqp, ids.queue))

    def record(number: int) -> None:
        event = IntegrationEvent(ids.client_id, "drill", f"receipt-{number}", ids.event_type, {"quantity": 1, "sku": ids.sku})
        with engine.begin() as connection:
            record_outbox_event(connection, event, datetime.now(timezone.utc))

    def relay_once():
        publisher = RabbitMqPublisher(amqp)
        try:
            return OutboxRelay(lambda: ClientScopedOutbox(engine, ids.client_id), publisher,
                               lambda: datetime.now(timezone.utc)).run_once()
        finally:
            publisher.close()

    def on_hand() -> int:
        return truth.scalar("SELECT on_hand FROM inventory_balances WHERE client_id = :c AND sku = :s", c=ids.client_id, s=ids.sku)

    def inbox_rows() -> int:
        return truth.scalar("SELECT count(*) FROM inbox_messages WHERE consumer_name = :n", n=ids.consumer_name)

    def outbox_statuses() -> dict[str, int]:
        rows = truth.rows("SELECT status, count(*) AS n FROM outbox_messages WHERE client_id = :c GROUP BY status", c=ids.client_id)
        return {row["status"]: row["n"] for row in rows}

    def run_child(name: str, *args: str) -> int:
        child = context.supervisor.start(name, [str(CHILD), *args], child_env(settings))
        try:
            return child.wait(timeout=CHILD_TIMEOUT_SECONDS)
        except Exception as error:  # subprocess.TimeoutExpired
            raise DrillFailure(f"{name} did not die within {CHILD_TIMEOUT_SECONDS}s") from error
        finally:
            context.supervisor.stop(child)

    def consume(expected: int) -> CountingConsumer:
        counting = CountingConsumer(consumer)
        deadline = time.monotonic() + 30
        runner_for(amqp, ids.queue, ids.event_type, counting).run(
            lambda: len(counting.results) >= expected or time.monotonic() > deadline, poll_seconds=0.5)
        return counting

    say("PART A: the consumer dies after COMMIT, before ACK")
    record(1)
    relay_once()
    say(f"one event is in the queue; stock on_hand = {on_hand()}")
    code_a = run_child("crashing consumer", "consume-then-crash", ids.client_id, ids.queue, ids.event_type, ids.consumer_name)
    wait_until(lambda: queue_counts(amqp, ids.queue) == (1, 0), 15)
    after_a = (on_hand(), inbox_rows(), *queue_counts(amqp, ids.queue))
    say(f"child exit code {code_a} (negative = killed by that signal; -9 is SIGKILL). stock on_hand = {after_a[0]}, inbox rows = {after_a[1]}, "
        f"queue ready = {after_a[2]}, consumers = {after_a[3]}")
    redelivered = consume(1)
    say(f"redelivery consumed: handler applied the effect again? {redelivered.results} "
        f"-> stock on_hand = {on_hand()}, inbox rows = {inbox_rows()}")

    say("\nPART B: the relay dies mid-batch, after publishing 2 of 3 events")
    for number in (2, 3, 4):
        record(number)
    code_b = run_child("crashing relay", "relay-then-crash", ids.client_id, "2")
    in_broker = queue_counts(amqp, ids.queue)[0]
    pending = outbox_statuses()
    say(f"child exit code {code_b}. outbox rows: {pending}; messages already in the broker: {in_broker}")
    result = relay_once()
    in_broker_after = queue_counts(amqp, ids.queue)[0]
    say(f"recovery relay pass: published {result.published}. outbox rows: {outbox_statuses()}; "
        f"broker now holds {in_broker_after} messages for 3 events")
    drained = consume(in_broker_after)
    totals = {"applied": drained.results.count(True), "absorbed by inbox": drained.results.count(False)}
    final = (on_hand(), inbox_rows())
    say(render_table(["deliveries", *totals, "stock on_hand", "inbox rows"],
                     [[len(drained.results), *totals.values(), final[0], final[1]]]))

    return Outcome((
        Check("the consumer process really died by SIGKILL after committing", code_a == -signal.SIGKILL),
        Check("the commit survived the crash (effect applied once) and the broker kept the message",
              after_a[:2] == (1, 1) and (after_a[2], after_a[3]) == (1, 0)),
        Check("the redelivery was absorbed by the inbox: handler skipped, stock still 1",
              redelivered.results == [False]),
        Check("the relay died by SIGKILL; its 3 rows stayed PENDING though 2 of them were already in the broker",
              code_b == -signal.SIGKILL and pending == {"PUBLISHED": 1, "PENDING": 3} and in_broker == 2),
        Check("the recovery relay re-published all 3 (the broker now holds 5 deliveries) and marked them PUBLISHED",
              result.published == 3 and in_broker_after == 5),
        Check("5 deliveries for 3 events: 3 applied, 2 absorbed; stock = 1 + 3 = 4, one inbox row per event",
              totals == {"applied": 3, "absorbed by inbox": 2} and final == (4, 4)),
    ))


DRILL = Drill(
    5, "crash-before-ack", "A worker crashes after commit but before ack; a relay crashes mid-batch",
    "A consumer commits its work to PostgreSQL and is killed (SIGKILL) before it acknowledges the message. "
    "Later the outbox relay is killed after publishing 2 of its 3 events, before marking any of them published.",
    "After the consumer crash: is the effect applied, and does the broker still hold the message? When "
    "it is redelivered, is the effect applied twice? After the relay crash: what status do the 3 outbox "
    "rows have, how many messages are in the broker, and what does stock end at after recovery?",
    Explanation(
        invariant="at-least-once delivery, exactly-once effect: stock equals the number of distinct events, "
                  "whatever the crashes",
        mechanism="the consumer acks only AFTER its transaction commits, and the inbox row (primary key "
                  "consumer + message id) commits in that same transaction, so a redelivery finds the row "
                  "and skips; the relay marks rows PUBLISHED only after the broker confirmed the publish, "
                  "inside one claim transaction, so a crash re-publishes the whole batch, never loses it",
        without="ack-before-commit loses the work on a crash; commit-without-inbox applies the effect "
                "again on every redelivery; mark-before-publish loses events the broker never received",
        trade_off="duplicates are normal, so EVERY handler must be idempotent and the inbox needs retention; "
                  "the relay holds row locks while publishing (small batches, short timeouts) and per-"
                  "aggregate ordering is best effort"),
    act)
