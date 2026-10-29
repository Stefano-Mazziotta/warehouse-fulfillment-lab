"""Run identity, cleanup scope and the context every drill receives."""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, text

from demo_gateways import PostgresTruth
from demo_ids import RunIds
from demo_processes import Supervisor
from demo_settings import Settings
from integrations.infrastructure.postgres_fake_sales_channel import PostgresFakeSalesChannel
from shipping.infrastructure.postgres_fake_carrier import PostgresFakeCarrier

ROOT_DIR = Path(__file__).resolve().parents[2]
DRILL_SERVICES = ("postgres", "rabbitmq", "valkey", "dynamodb-local")

# Dependents first. Every statement is scoped to one drill's client, consumer or id prefix, and
# `PostgresTruth.delete_run` (run after these) removes the orders, stock and outbox rows.
DELETE_STATEMENTS = (
    "DELETE FROM inbox_messages WHERE consumer_name = 'channel-order-ingest' AND message_id IN "
    "(SELECT id FROM integration_events WHERE client_id = :c)",
    "DELETE FROM inbox_messages WHERE consumer_name = 'edi-order-intake' AND message_id LIKE :prefix",
    "DELETE FROM inbox_messages WHERE consumer_name = :drill",
    "DELETE FROM channel_order_versions WHERE client_id = :c",
    "DELETE FROM integration_events WHERE client_id = :c",
    "DELETE FROM integration_checkpoints WHERE client_id = :c",
    "DELETE FROM fake_channel_orders WHERE client_id = :c",
)


class DrillIds(RunIds):
    """The demo's run ids, re-keyed so a drill's rows are never mistaken for a demo's."""

    @property
    def client_id(self) -> str:
        # 15 characters: drill 8 sends it as the EDI sender, whose ISA06 field is 15 wide.
        return f"D{self.run_id}"

    @property
    def order_id(self) -> str:
        return f"ORD-{self.run_id}"

    def order(self, label: str) -> str:
        return f"ORD-{label}-{self.run_id}"

    @property
    def consumer_name(self) -> str:
        return f"drill-{self.run_id}"

    @property
    def queue(self) -> str:
        return f"drill.{self.run_id}"

    @property
    def event_type(self) -> str:
        return f"DrillStockReceived.{self.run_id}"


def new_drill_ids(now: datetime, token: str) -> DrillIds:
    return DrillIds(f"{now:%m%d%H%M%S}{token}")


def missing_drill_services(settings: Settings, is_open: Callable[[str, int], bool]) -> list[str]:
    endpoints = settings.endpoints()
    return [name for name in DRILL_SERVICES if not is_open(*endpoints[name])]


class DrillTruth(PostgresTruth):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        # Lab fakes live outside Alembic; the API creates them the same way at start-up.
        PostgresFakeSalesChannel.install(engine)
        PostgresFakeCarrier.install(engine)

    def rows(self, sql: str, **params) -> list[dict]:
        with self._engine.connect() as connection:
            return [dict(row) for row in connection.execute(text(sql), params).mappings()]

    def scalar(self, sql: str, **params):
        with self._engine.connect() as connection:
            return connection.execute(text(sql), params).scalar_one()

    def delete_drill(self, ids: DrillIds) -> None:
        params = {"c": ids.client_id, "prefix": f"{ids.client_id}:%", "drill": ids.consumer_name}
        with self._engine.begin() as connection:
            for statement in DELETE_STATEMENTS:
                connection.execute(text(statement), params)
        self.delete_run(ids)


@dataclass
class DrillContext:
    ids: DrillIds
    settings: Settings
    engine: Engine
    truth: DrillTruth
    supervisor: Supervisor
    say: Callable[[str], None]
    cleanups: list[Callable[[], None]] = field(default_factory=list)

    def defer(self, cleanup: Callable[[], None]) -> None:
        self.cleanups.append(cleanup)

    def close(self) -> list[Exception]:
        """Run every deferred cleanup, newest first, even when one fails; return what failed."""
        failures: list[Exception] = []
        while self.cleanups:
            try:
                self.cleanups.pop()()
            except Exception as error:  # noqa: BLE001 - one broken cleanup must not strand the rest
                failures.append(error)
        return failures
