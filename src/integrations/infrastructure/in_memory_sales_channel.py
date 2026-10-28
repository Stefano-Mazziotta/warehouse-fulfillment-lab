from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone

from integrations.domain.channel_cursor import ChannelCursor
from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order import ChannelOrder
from integrations.domain.channel_order_line import ChannelOrderLine
from integrations.domain.channel_order_page import ChannelOrderPage

from .channel_webhooks import ChannelWebhooks


class InMemorySalesChannel:
    """Fake source of truth for channel orders."""

    def __init__(
        self,
        webhooks: ChannelWebhooks,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.webhooks = webhooks
        self._clock = clock
        self._orders: dict[tuple[str, str], ChannelOrder] = {}

    def upsert(
        self,
        client_id: str,
        channel_order_id: str,
        warehouse_id: str,
        lines: Sequence[ChannelOrderLine],
        *,
        updated_at: datetime | None = None,
    ) -> ChannelEvent:
        previous = self._orders.get((client_id, channel_order_id))
        order = ChannelOrder(
            client_id, channel_order_id, warehouse_id, tuple(lines),
            previous.version + 1 if previous else 1, updated_at or self._clock(),
        )
        self._orders[(client_id, channel_order_id)] = order
        return self.webhooks.publish(order)

    def rewrite_without_version_bump(
        self, client_id: str, channel_order_id: str, lines: Sequence[ChannelOrderLine],
        *, minutes: int | None = None,
    ) -> None:
        """Simulate a channel bug: content changes, version does not."""
        order = self._orders[(client_id, channel_order_id)]
        updated_at = order.updated_at
        if minutes is not None:
            from datetime import timedelta
            updated_at = order.updated_at.replace(hour=12, minute=0) + timedelta(minutes=minutes)
        self._orders[(client_id, channel_order_id)] = replace(
            order, lines=tuple(lines), updated_at=updated_at
        )

    def list_orders_updated_since(
        self, client_id: str, cursor: ChannelCursor | None, limit: int
    ) -> ChannelOrderPage:
        ordered = sorted(
            (o for o in self._orders.values() if o.client_id == client_id
             and (cursor is None or ChannelCursor.after(o) > cursor)),
            key=lambda o: (o.updated_at, o.channel_order_id),
        )
        return ChannelOrderPage(tuple(ordered[:limit]), len(ordered) > limit)
