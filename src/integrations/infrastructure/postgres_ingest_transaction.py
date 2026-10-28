from typing import Any, Mapping

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert

from integrations.domain.channel_order import ChannelOrder
from integrations.domain.channel_order_record import ChannelOrderRecord
from integrations.domain.integration_event_status import IntegrationEventStatus
from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction

from .integrations_schema import channel_order_versions as versions, integration_events


def _identity(source: str, client_id: str, channel_order_id: str):
    return and_(
        versions.c.source == source,
        versions.c.client_id == client_id,
        versions.c.channel_order_id == channel_order_id,
    )


class PostgresIngestTransaction(PostgresOrderTransaction):

    # Same SQL as the shared inbox; it only needs `_connection()`.
    record_inbox = PostgresInboxTransaction.record_inbox

    def save_received_event(
        self, event_id: str, source: str, client_id: str, payload: Mapping[str, Any]
    ) -> None:
        self._connection().execute(
            insert(integration_events)
            .values(id=event_id, source=source, client_id=client_id, payload=payload,
                    status=IntegrationEventStatus.RECEIVED.value, received_at=self._clock())
            .on_conflict_do_nothing(index_elements=["id"])
        )

    def finish_event(
        self, event_id: str, status: IntegrationEventStatus, detail: str | None
    ) -> None:
        self._connection().execute(
            update(integration_events)
            .where(integration_events.c.id == event_id)
            .values(status=status.value, detail=detail, processed_at=self._clock())
        )

    def lock_channel_version(
        self, source: str, client_id: str, channel_order_id: str
    ) -> ChannelOrderRecord | None:
        row = self._connection().execute(
            select(versions).where(_identity(source, client_id, channel_order_id)).with_for_update()
        ).mappings().first()
        return None if row is None else ChannelOrderRecord(row["version"], row["content"])

    def claim_channel_version(self, source: str, order: ChannelOrder) -> bool:
        statement = (
            insert(versions)
            .values(source=source, client_id=order.client_id,
                    channel_order_id=order.channel_order_id,
                    version=order.version, content=order.content())
            .on_conflict_do_nothing()
            .returning(versions.c.version)
        )
        return self._connection().execute(statement).scalar_one_or_none() is not None

    def advance_channel_version(self, source: str, order: ChannelOrder) -> None:
        self._connection().execute(
            update(versions)
            .where(_identity(source, order.client_id, order.channel_order_id))
            .values(version=order.version, content=order.content())
        )
