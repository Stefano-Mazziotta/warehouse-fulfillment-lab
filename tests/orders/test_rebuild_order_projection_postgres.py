"""Replaying the real outbox into real DynamoDB Local: PostgreSQL is only ever read."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from messaging.domain.fulfillment_events import (
    order_allocated, order_cancelled, order_packed, order_shipped, picking_completed,
)
from messaging.infrastructure.messaging_schema import outbox_messages
from messaging.infrastructure.outbox_recording import record_outbox_event
from orders.application.rebuild_order_projection import RebuildOrderProjection
from orders.domain import OrderStatus
from orders.infrastructure.dynamodb_order_projection import DynamoDbOrderProjection
from orders.infrastructure.order_projection_cli import main
from orders.infrastructure.postgres_outbox_order_events import PostgresOutboxOrderEvents

from order_projection_support import update  # noqa: I001  (extends sys.path)
from in_memory_messaging import START


@pytest.fixture
def projection(dynamodb_url):
    real = DynamoDbOrderProjection(dynamodb_url, table_name=f"lab_test_{uuid4().hex}")
    real.install()
    try:
        yield real
    finally:
        real.drop()


def record(engine, *events):
    with engine.begin() as connection:
        for position, event in enumerate(events):
            record_outbox_event(connection, event, START + timedelta(seconds=position))


def outbox_snapshot(engine):
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(
            select(outbox_messages).order_by(outbox_messages.c.message_id)).mappings()]


def test_the_source_replays_order_events_oldest_first(orders_database):
    record(orders_database, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]),
           picking_completed("owner", "o1"))
    assert [m.event_type for m in PostgresOutboxOrderEvents(orders_database).events()] == [
        "OrderAllocated", "PickingCompleted"]


def test_a_dropped_projection_is_rebuilt_from_the_outbox(orders_database, projection):
    record(orders_database,
           order_allocated("owner", "o1", "w1", [("l1", "sku", 2)]),
           order_allocated("owner", "o2", "w1", [("l1", "sku", 1)]),
           order_allocated("other", "o1", "w2", [("l1", "sku", 1)]),
           picking_completed("owner", "o1"),
           order_cancelled("owner", "o2"),
           order_packed("owner", "o1", ["p1", "p2"]),
           order_shipped("owner", "o1", "attempt", "trk-1", ["p1", "p2"]))
    rebuild = RebuildOrderProjection(projection, PostgresOutboxOrderEvents(orders_database))
    assert rebuild.run() == 7
    expected = {owner: projection.list_for_client(owner) for owner in ("owner", "other")}
    assert [view.status for view in expected["owner"]] == [OrderStatus.SHIPPED, OrderStatus.CANCELLED]

    projection.drop()           # the projection is lost entirely
    rebuild.run()               # reset recreates the table, then the outbox is replayed
    assert {owner: projection.list_for_client(owner) for owner in ("owner", "other")} == expected
    assert projection.get("owner", "o1").tracking_number == "trk-1"


def test_rebuild_never_writes_to_postgresql(orders_database, projection):
    record(orders_database, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]),
           order_packed("owner", "o1", ["p1"]))
    before = outbox_snapshot(orders_database)
    RebuildOrderProjection(projection, PostgresOutboxOrderEvents(orders_database)).run()
    assert outbox_snapshot(orders_database) == before
    assert {row["status"] for row in before} == {"PENDING"}


def test_rebuild_replaces_stale_projection_content(orders_database, projection):
    projection.apply(update("SHIPPED", order_id="ghost", package_count=1, tracking_number="x"))
    record(orders_database, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]))
    RebuildOrderProjection(projection, PostgresOutboxOrderEvents(orders_database)).run()
    assert projection.get("owner", "ghost") is None
    assert projection.get("owner", "o1").status == OrderStatus.ALLOCATED


def test_the_rebuild_command_reads_the_outbox_of_the_configured_database(
    orders_database, projection, dynamodb_url, capsys
):
    record(orders_database, order_allocated("owner", "o1", "w1", [("l1", "sku", 1)]))
    with orders_database.connect() as connection:
        schema = connection.scalar(text("select current_schema()"))
    url = orders_database.url.set(query={"options": f"-csearch_path={schema}"})
    environ = {"LAB_DATABASE_URL": url.render_as_string(hide_password=False),
               "LAB_DYNAMODB_URL": dynamodb_url}
    # The command targets the default table; clean it up so the run leaves nothing behind.
    default = DynamoDbOrderProjection(dynamodb_url)
    try:
        assert main(["rebuild"], environ) == 0
        assert default.get("owner", "o1").status == OrderStatus.ALLOCATED
    finally:
        default.drop()
    assert "replayed 1 order events" in capsys.readouterr().out


def test_the_command_names_the_settings_it_is_missing(capsys):
    assert main(["run"], {"LAB_DATABASE_URL": "x"}) == 2
    assert "LAB_DYNAMODB_URL, LAB_AMQP_URL" in capsys.readouterr().err
    assert main(["explode"], {}) == 2


def test_events_of_one_transaction_replay_in_lifecycle_order_whatever_their_ids(orders_database):
    # One business transaction stamps the same created_at on every event it records.
    with orders_database.begin() as connection:
        for event in (order_shipped("owner", "o1", "attempt", "trk-1", ["p1"]),
                      order_packed("owner", "o1", ["p1"]),
                      picking_completed("owner", "o1"),
                      order_allocated("owner", "o1", "w1", [("l1", "sku", 1)])):
            record_outbox_event(connection, event, START)
        for position, event_type in enumerate(
            ("OrderShipped", "OrderPacked", "PickingCompleted", "OrderAllocated")
        ):
            # Ids sort against the lifecycle, so id order alone would replay it backwards.
            connection.execute(text("update outbox_messages set message_id = :new where event_type = :type"),
                               {"new": f"id-{position}", "type": event_type})

    replayed = [m.event_type for m in PostgresOutboxOrderEvents(orders_database).events()]

    assert replayed == ["OrderAllocated", "PickingCompleted", "OrderPacked", "OrderShipped"]
