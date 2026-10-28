from typing import Protocol

from integrations.domain.channel_cursor import ChannelCursor
from integrations.domain.channel_order_page import ChannelOrderPage


class SalesChannelPort(Protocol):
    def list_orders_updated_since(
        self, client_id: str, cursor: ChannelCursor | None, limit: int
    ) -> ChannelOrderPage:
        """Orders strictly after the cursor, ordered by (updated_at, channel_order_id)."""
