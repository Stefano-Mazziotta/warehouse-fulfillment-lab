"""Wiring of the real PostgreSQL adapters for the integration proofs."""
import time

import pytest
from sqlalchemy import select, text

from integrations.application.receive_channel_event import ReceiveChannelEvent
from integrations.application.reconcile_channel_orders import ReconcileChannelOrders
from integrations.infrastructure.channel_webhooks import ChannelWebhooks
from integrations.infrastructure.integrations_schema import (
    channel_order_versions, integration_checkpoints, integration_events,
)
from integrations.infrastructure.postgres_fake_sales_channel import PostgresFakeSalesChannel
from integrations.infrastructure.postgres_ingest_transaction import PostgresIngestTransaction
from integrations.infrastructure.postgres_reconciliation_transaction import (
    PostgresReconciliationTransaction,
)
from orders.infrastructure.order_schema import orders

from channel_support import SOURCE, T0


class PostgresLab:
    def __init__(self, engine, overlap=None, page_size=50):
        from datetime import timedelta
        self.engine = engine
        PostgresFakeSalesChannel.install(engine)
        self.webhooks = ChannelWebhooks()
        self.channel = PostgresFakeSalesChannel(engine, self.webhooks, clock=lambda: T0)
        self.receive = ReceiveChannelEvent(lambda: PostgresIngestTransaction(engine), SOURCE)
        self.webhooks.subscribe(self.receive.execute)
        self.reconcile = ReconcileChannelOrders(
            self.channel, self.receive, lambda: PostgresReconciliationTransaction(engine), SOURCE,
            page_size=page_size, overlap=overlap if overlap is not None else timedelta(minutes=10),
            clock=lambda: T0)

    def order_ids(self):
        with self.engine.connect() as connection:
            return sorted(connection.scalars(select(orders.c.order_id)))

    def events(self):
        with self.engine.connect() as connection:
            return {r.id: r for r in connection.execute(select(integration_events))}

    def checkpoint(self, client="owner"):
        with self.engine.connect() as connection:
            return connection.scalar(select(integration_checkpoints.c.cursor).where(
                integration_checkpoints.c.client_id == client))

    def versions(self):
        with self.engine.connect() as connection:
            return {(r.client_id, r.channel_order_id): r.version
                    for r in connection.execute(select(channel_order_versions))}


def wait_for_checkpoint_lock_wait(engine):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            if observer.scalar(text(
                    "select exists(select 1 from pg_stat_activity where wait_event_type = 'Lock' "
                    "and cardinality(pg_blocking_pids(pid)) > 0 "
                    "and query ilike '%integration_checkpoints%')")):
                return
        time.sleep(0.02)
    pytest.fail("second reconciler never demonstrably waited on the checkpoint lock")
