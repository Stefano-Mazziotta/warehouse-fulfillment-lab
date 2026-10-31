from contextlib import nullcontext

from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order import ChannelOrder
from integrations.domain.channel_order_record import ChannelOrderRecord
from integrations.domain.ingest_outcome import IngestOutcome
from orders.application.create_order import CreateOrder
from orders.domain import Order, OrderError, OrderKey, OrderLine

from .ingest_transaction import IngestTransaction


class IngestChannelOrder:
    """Map a channel order onto the WMS order, deciding by channel version.

    The WMS order ID is the channel order ID. Rules, per (source, owner, order):
    - unknown: create the order (CreateOrder is idempotent) and remember the version;
    - older version than known: stale, ignored;
    - same or newer version with identical content: nothing to do (newer only
      advances the remembered version);
    - same or newer version with DIFFERENT content: conflict, reported and never
      applied, because the warehouse may already be allocating the original.
    """

    def __init__(self, source: str) -> None:
        self._source = source

    def execute(self, transaction: IngestTransaction, event: ChannelEvent) -> tuple[IngestOutcome, str | None]:
        incoming = event.order
        known = transaction.lock_channel_version(
            self._source, incoming.client_id, incoming.channel_order_id
        )
        if known is None:
            try:
                # Reuse the existing use case inside this transaction.
                CreateOrder(lambda: nullcontext(transaction)).execute(self._to_order(incoming))
            except OrderError:
                return IngestOutcome.CONFLICT, "WMS order exists with a different payload"
            if transaction.claim_channel_version(self._source, incoming):
                return IngestOutcome.CREATED, None
            # A concurrent ingest of the same order won the race; judge against it.
            known = transaction.lock_channel_version(
                self._source, incoming.client_id, incoming.channel_order_id
            )
            assert known is not None
        return self._compare(transaction, known, incoming)

    def _compare(
        self, transaction: IngestTransaction, known: ChannelOrderRecord, incoming: ChannelOrder
    ) -> tuple[IngestOutcome, str | None]:
        if incoming.version < known.version:
            return IngestOutcome.STALE_IGNORED, None
        if incoming.content() != known.content:
            return IngestOutcome.CONFLICT, (
                f"version {incoming.version} differs from accepted version {known.version}"
            )
        if incoming.version > known.version:
            transaction.advance_channel_version(self._source, incoming)
        return IngestOutcome.ALREADY_KNOWN, None

    @staticmethod
    def _to_order(channel_order: ChannelOrder) -> Order:
        return Order(
            OrderKey(channel_order.client_id, channel_order.channel_order_id),
            channel_order.warehouse_id,
            tuple(
                OrderLine(line.line_id, line.sku, line.quantity)
                for line in channel_order.lines
            ),
        )
