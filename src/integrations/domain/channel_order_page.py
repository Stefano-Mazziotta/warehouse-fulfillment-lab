from dataclasses import dataclass

from .channel_cursor import ChannelCursor
from .channel_order import ChannelOrder


@dataclass(frozen=True)
class ChannelOrderPage:

    orders: tuple[ChannelOrder, ...]
    has_more: bool

    @property
    def next_cursor(self) -> ChannelCursor | None:
        return ChannelCursor.after(self.orders[-1]) if self.orders else None
