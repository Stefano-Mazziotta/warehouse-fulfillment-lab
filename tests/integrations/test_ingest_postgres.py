"""Ingest against real PostgreSQL: atomicity, persistence and the migration."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError

from integrations.domain.channel_event import ChannelEvent
from integrations.domain.ingest_outcome import IngestOutcome as Outcome

from channel_support import SOURCE, channel_order
from integration_postgres_support import PostgresLab


@pytest.fixture
def lab(orders_database):
    return PostgresLab(orders_database)


def test_webhook_creates_order_event_and_version_together(lab):
    assert lab.receive.execute(ChannelEvent("evt-1", channel_order())) is Outcome.CREATED
    assert lab.order_ids() == ["c1"]
    assert lab.events()["evt-1"].status == "PROCESSED"
    assert lab.versions() == {("owner", "c1"): 1}


def test_duplicate_event_and_retry_with_a_new_event_id_create_one_order(lab):
    assert lab.receive.execute(ChannelEvent("evt-1", channel_order())) is Outcome.CREATED
    assert lab.receive.execute(ChannelEvent("evt-1", channel_order())) is Outcome.DUPLICATE_EVENT
    assert lab.receive.execute(ChannelEvent("evt-2", channel_order())) is Outcome.ALREADY_KNOWN
    assert lab.order_ids() == ["c1"]


def test_conflicts_are_stored_as_failed_events_and_never_overwrite(lab):
    lab.receive.execute(ChannelEvent("evt-1", channel_order()))
    changed = channel_order(lines=(("l1", "sku", 9),))
    assert lab.receive.execute(ChannelEvent("evt-2", changed)) is Outcome.CONFLICT
    event_row = lab.events()["evt-2"]
    assert (event_row.status, event_row.payload["lines"][0]["quantity"]) == ("FAILED", 9)
    with lab.engine.connect() as connection:
        assert connection.scalar(text("select quantity from order_lines")) == 1


def test_stale_version_does_not_regress_state(lab):
    lab.receive.execute(ChannelEvent("evt-2", channel_order(version=2, minutes=2)))
    assert lab.receive.execute(ChannelEvent("evt-1", channel_order(version=1))) is Outcome.STALE_IGNORED
    assert lab.versions() == {("owner", "c1"): 2}


def test_failure_after_the_order_insert_rolls_back_order_inbox_and_version_but_keeps_the_event(lab):
    def crash(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("INSERT INTO CHANNEL_ORDER_VERSIONS"):
            raise RuntimeError("crash after order insert")

    event.listen(lab.engine, "before_cursor_execute", crash)
    try:
        with pytest.raises(RuntimeError):
            lab.receive.execute(ChannelEvent("evt-1", channel_order()))
    finally:
        event.remove(lab.engine, "before_cursor_execute", crash)
    assert lab.order_ids() == [] and lab.versions() == {}
    assert lab.events()["evt-1"].status == "RECEIVED"
    with lab.engine.connect() as connection:
        assert connection.scalar(text("select count(*) from inbox_messages")) == 0
    assert lab.receive.execute(ChannelEvent("evt-1", channel_order())) is Outcome.CREATED
    assert lab.events()["evt-1"].status == "PROCESSED"


def test_concurrent_events_for_one_order_create_it_once(lab):
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(lab.receive.execute, ChannelEvent(f"evt-{n}", channel_order()))
                   for n in range(4)]
        outcomes = [future.result(10) for future in futures]
    assert outcomes.count(Outcome.CREATED) == 1
    assert set(outcomes) <= {Outcome.CREATED, Outcome.ALREADY_KNOWN}
    assert lab.order_ids() == ["c1"]


def test_version_rows_require_an_existing_order_and_the_migration_round_trips(lab):
    with pytest.raises(IntegrityError), lab.engine.begin() as connection:
        connection.execute(text(
            "insert into channel_order_versions values ('s', 'owner', 'ghost', 1, '{}')"))
    config = Config("alembic.ini")
    with lab.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0006_messaging")
    assert "integration_events" not in inspect(lab.engine).get_table_names()
    with lab.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    assert {"integration_events", "integration_checkpoints", "channel_order_versions"} <= set(
        inspect(lab.engine).get_table_names())
