from collections.abc import Callable
from contextlib import AbstractContextManager

from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order import ChannelOrder
from integrations.domain.ingest_outcome import IngestOutcome
from integrations.domain.integration_event_status import IntegrationEventStatus
from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.inbound_message import InboundMessage

from .ingest_channel_order import IngestChannelOrder
from .ingest_transaction import IngestTransaction

CONSUMER_NAME = "channel-order-ingest"


class ReceiveChannelEvent:
    """Persist the raw event first, then process it once through the inbox.

    If processing fails, the RECEIVED row remains as evidence and the inbox row
    rolls back, so a redelivery or a reconciliation run can retry.
    """

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[IngestTransaction]], source: str
    ) -> None:
        self._transaction = transaction
        self._source = source
        self._ingest = IngestChannelOrder(source)

    def execute(self, event: ChannelEvent) -> IngestOutcome:
        with self._transaction() as transaction:
            stored = transaction.save_received_event(
                event.event_id, self._source, event.order.client_id, event.order.to_payload()
            )
        # The first stored payload wins: a retry of this event ID with another body
        # must not be processed under, or marked as, the original evidence.
        order = ChannelOrder.from_payload(stored)
        outcomes: list[IngestOutcome] = []

        def handle(transaction: IngestTransaction, message: InboundMessage) -> None:
            outcome, detail = self._ingest.execute(transaction, ChannelEvent(event.event_id, order))
            status = (
                IntegrationEventStatus.FAILED
                if outcome is IngestOutcome.CONFLICT
                else IntegrationEventStatus.PROCESSED
            )
            transaction.finish_event(event.event_id, status, detail)
            outcomes.append(outcome)

        message = InboundMessage(
            event.event_id, "ChannelOrderUpdated", order.client_id, stored
        )
        consumer = IdempotentConsumer(self._transaction, CONSUMER_NAME, handle)
        return outcomes[0] if consumer.handle(message) else IngestOutcome.DUPLICATE_EVENT
