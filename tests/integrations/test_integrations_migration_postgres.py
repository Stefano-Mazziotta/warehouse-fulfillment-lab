"""The 0007 downgrade refuses to drop reconciliation state."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from integrations.domain.channel_event import ChannelEvent

from channel_support import channel_order
from integration_postgres_support import PostgresLab

INTEGRATION_TABLES = {"integration_events", "integration_checkpoints", "channel_order_versions"}


def migrate(engine, direction, revision):
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, direction)(config, revision)


def version(engine):
    with engine.connect() as connection:
        return connection.scalar(text("select version_num from alembic_version"))


def seed_event(engine):
    with engine.begin() as connection:
        connection.execute(text(
            "insert into integration_events (id, source, client_id, payload, status, received_at) "
            "values ('e1', 's', 'owner', '{}', 'RECEIVED', now())"))


def seed_checkpoint(engine):
    with engine.begin() as connection:
        connection.execute(text(
            "insert into integration_checkpoints (source, client_id, updated_at) "
            "values ('s', 'owner', now())"))


def seed_version(engine):
    PostgresLab(engine).receive.execute(ChannelEvent("evt-1", channel_order()))
    with engine.begin() as connection:
        connection.execute(text("delete from integration_events"))


@pytest.mark.parametrize("seed", [seed_event, seed_checkpoint, seed_version],
                         ids=["event", "checkpoint", "channel-version"])
def test_downgrade_refuses_to_discard_integration_state(orders_database, seed):
    engine = orders_database
    seed(engine)
    with pytest.raises(RuntimeError, match="discard integration"):
        migrate(engine, "downgrade", "0006_messaging")
    assert version(engine) == "0007_integrations"
    assert INTEGRATION_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text(
            "select (select count(*) from integration_events) "
            "+ (select count(*) from integration_checkpoints) "
            "+ (select count(*) from channel_order_versions)")) == 1


def test_empty_downgrade_succeeds_and_roundtrips(orders_database):
    engine = orders_database
    migrate(engine, "downgrade", "0006_messaging")
    assert not INTEGRATION_TABLES & set(inspect(engine).get_table_names())
    migrate(engine, "upgrade", "head")
    assert version(engine) == "0007_integrations"
    assert INTEGRATION_TABLES <= set(inspect(engine).get_table_names())
