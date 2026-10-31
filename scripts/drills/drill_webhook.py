"""Drill 3: the same webhook is delivered twice (and then five times at once)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.app_config import AppConfig
from api.app_factory import create_app
from demo_format import render_table
from drill_context import DrillContext
from drill_core import Check, Drill, Explanation, Outcome
from drill_verdicts import tally

CONCURRENT_DELIVERIES = 5


def event_body(context: DrillContext, event_id: str, channel_order_id: str) -> dict:
    ids = context.ids
    return {"event_id": event_id, "order": {
        "client_id": ids.client_id, "channel_order_id": channel_order_id, "warehouse_id": ids.warehouse_id,
        "version": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
        "lines": [{"line_id": ids.line_id, "sku": ids.sku, "quantity": 2}]}}


def act(context: DrillContext) -> Outcome:
    ids, engine, say, truth = context.ids, context.engine, context.say, context.truth
    app = create_app(AppConfig(database_url=context.settings.database_url), engine=engine)

    def deliver(body: dict) -> str:
        response = app.test_client().post("/webhooks/sales-channel", json=body)
        return f"HTTP {response.status_code} {response.get_json()['outcome']}"

    event_id, order_id = f"evt-{ids.run_id}-1", ids.order("W1")
    body = event_body(context, event_id, order_id)

    def evidence(event: str, order: str) -> dict:
        return {
            "integration_events": truth.scalar("SELECT count(*) FROM integration_events WHERE id = :e", e=event),
            "inbox rows": truth.scalar(
                "SELECT count(*) FROM inbox_messages WHERE consumer_name = 'channel-order-ingest' AND message_id = :e", e=event),
            "orders": truth.scalar("SELECT count(*) FROM orders WHERE client_id = :c AND order_id = :o", c=ids.client_id, o=order),
        }

    first, second = deliver(body), deliver(body)
    one = evidence(event_id, order_id)
    say(f"delivery 1 of {event_id}: {first}\ndelivery 2 of {event_id}: {second}")
    say(render_table(list(one), [list(one.values())]))

    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO inbox_messages (consumer_name, message_id) VALUES ('channel-order-ingest', :e)"), {"e": event_id})
        constraint = "(no error: the duplicate row was accepted!)"
    except IntegrityError as error:
        constraint = f"{type(error.orig).__name__} on constraint {error.orig.diag.constraint_name}"
    say(f"writing the same inbox row by hand is refused by the database: {constraint}")

    burst_id, burst_order = f"evt-{ids.run_id}-2", ids.order("W2")
    burst_body = event_body(context, burst_id, burst_order)
    with ThreadPoolExecutor(max_workers=CONCURRENT_DELIVERIES) as pool:
        burst = list(pool.map(lambda _: deliver(burst_body), range(CONCURRENT_DELIVERIES)))
    many = evidence(burst_id, burst_order)
    outcomes = tally([line.split(" ", 2)[2] for line in burst])
    say(f"{CONCURRENT_DELIVERIES} simultaneous deliveries of {burst_id}: {outcomes}")
    say(render_table(list(many), [list(many.values())]))

    return Outcome((
        Check("the first delivery created the order; the second was acknowledged as DUPLICATE_EVENT",
              first.endswith("CREATED") and second.endswith("DUPLICATE_EVENT") and first.startswith("HTTP 202")
              and second.startswith("HTTP 202")),
        Check("one stored event, one inbox row and one order for the doubled delivery",
              list(one.values()) == [1, 1, 1]),
        Check("the database itself rejects a second inbox row with the same (consumer, message id)",
              "UniqueViolation" in constraint),
        Check(f"{CONCURRENT_DELIVERIES} simultaneous deliveries: exactly one CREATED, the rest DUPLICATE_EVENT",
              outcomes == {"CREATED": 1, "DUPLICATE_EVENT": CONCURRENT_DELIVERIES - 1}),
        Check("still one stored event, one inbox row and one order after the burst", list(many.values()) == [1, 1, 1]),
    ))


DRILL = Drill(
    3, "duplicate-webhook", "A webhook is delivered twice",
    "The sales channel POSTs 'order created' to /webhooks/sales-channel. Its retry logic did not see our "
    "202, so it sends the same event id again. Then five copies of another event arrive at the same instant.",
    "What does the second delivery return, and what is in the database afterwards (events, inbox, orders)? "
    "What decides who wins when five copies race?",
    Explanation(
        invariant="one event id, one effect: duplicates are acknowledged but change nothing",
        mechanism="the raw event is stored first (ON CONFLICT DO NOTHING on its id), then the handler runs "
                  "inside IdempotentConsumer: an inbox row with primary key (consumer, message_id) is written "
                  "in the SAME transaction as the order, and a concurrent duplicate waits on that unique "
                  "index, then conflicts",
        without="every redelivery creates (or re-applies) the order: duplicate orders, double allocation, "
                "double shipments; a plain 'check then insert' races between the check and the insert",
        trade_off="the inbox grows forever without retention; the duplicate is answered 202 (not an error) "
                  "so senders stop retrying, which also hides a sender bug that reuses ids for different content"),
    act)
