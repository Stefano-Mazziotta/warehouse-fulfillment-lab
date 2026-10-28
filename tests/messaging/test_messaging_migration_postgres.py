"""The 0006 downgrade refuses to drop undelivered or deduplication state."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

MESSAGING_TABLES = {"outbox_messages", "inbox_messages"}
OUTBOX_ROW = (
    "insert into outbox_messages (message_id, client_id, aggregate_type, aggregate_id, event_type, "
    "payload, created_at, status, next_attempt_at) "
    "values ('m1', 'owner', 'order', 'o1', 'OrderCreated', '{}', now(), :status, now())")
INBOX_ROW = "insert into inbox_messages (consumer_name, message_id) values ('c', 'm1')"


def migrate(engine, direction, revision):
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, direction)(config, revision)


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("select version_num from alembic_version"))


@pytest.mark.parametrize("statement, params", [
    (OUTBOX_ROW, {"status": "PENDING"}),
    (OUTBOX_ROW, {"status": "DEAD"}),
    (INBOX_ROW, {}),
], ids=["pending-outbox", "dead-outbox", "inbox"])
def test_downgrade_refuses_to_discard_messaging_state(orders_database, statement, params):
    engine = orders_database
    with engine.begin() as connection:
        connection.execute(text(statement), params)
    with pytest.raises(RuntimeError, match="discard messaging"):
        migrate(engine, "downgrade", "0005_shipping")
    assert version(engine) == "0007_integrations"
    assert MESSAGING_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        rows = connection.scalar(text(
            "select (select count(*) from outbox_messages) + (select count(*) from inbox_messages)"))
    assert rows == 1


def test_downgrade_keeps_published_history_out_of_the_way_and_roundtrips(orders_database):
    engine = orders_database
    with engine.begin() as connection:
        connection.execute(text(OUTBOX_ROW), {"status": "PUBLISHED"})
    migrate(engine, "downgrade", "0005_shipping")
    assert not MESSAGING_TABLES & set(inspect(engine).get_table_names())
    migrate(engine, "upgrade", "head")
    assert version(engine) == "0007_integrations"
    assert MESSAGING_TABLES <= set(inspect(engine).get_table_names())
