from dataclasses import dataclass
from datetime import datetime, timedelta

from .channel_order import ChannelOrder


@dataclass(frozen=True, order=True)
class ChannelCursor:
    """Keyset position: (updated_at, id) is unique, so ties on time never skip an order.

    A real API would hand back an opaque token. This one is readable because the
    overlap window needs to move the position back in time.
    """

    updated_at: datetime
    order_id: str

    @staticmethod
    def after(order: ChannelOrder) -> "ChannelCursor":
        return ChannelCursor(order.updated_at, order.channel_order_id)

    def minus(self, overlap: timedelta) -> "ChannelCursor":
        # An empty ID sorts before every real ID, so the whole instant is re-read.
        return ChannelCursor(self.updated_at - overlap, "")

    def to_token(self) -> str:
        return f"{self.updated_at.isoformat()}|{self.order_id}"

    @staticmethod
    def from_token(token: str) -> "ChannelCursor":
        moment, _, order_id = token.partition("|")
        return ChannelCursor(datetime.fromisoformat(moment), order_id)
