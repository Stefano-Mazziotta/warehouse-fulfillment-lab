from typing import Any, Mapping, Protocol

from integrations.domain.channel_order import ChannelOrder
from integrations.domain.channel_order_record import ChannelOrderRecord
from integrations.domain.integration_event_status import IntegrationEventStatus
from messaging.application.inbox_transaction import InboxTransaction
from orders.application.order_transaction import OrderTransaction


class IngestTransaction(InboxTransaction, OrderTransaction, Protocol):
    """Inbox row, WMS order and channel bookkeeping commit or roll back together."""

    def save_received_event(
        self, event_id: str, source: str, client_id: str, payload: Mapping[str, Any]
    ) -> None: ...

    def finish_event(
        self, event_id: str, status: IntegrationEventStatus, detail: str | None
    ) -> None: ...

    def lock_channel_version(
        self, source: str, client_id: str, channel_order_id: str
    ) -> ChannelOrderRecord | None: ...

    def claim_channel_version(self, source: str, order: ChannelOrder) -> bool:
        """False when a concurrent ingest already recorded this channel order."""

    def advance_channel_version(self, source: str, order: ChannelOrder) -> None: ...
