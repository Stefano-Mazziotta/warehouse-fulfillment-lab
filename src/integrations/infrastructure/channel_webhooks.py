from collections.abc import Callable
from uuid import uuid4

from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order import ChannelOrder


class ChannelWebhooks:
    """Fake webhook delivery with the failure modes a real channel produces."""

    def __init__(self) -> None:
        self.drop = False
        self.errors: list[Exception] = []
        self._subscriber: Callable[[ChannelEvent], object] | None = None

    def subscribe(self, subscriber: Callable[[ChannelEvent], object]) -> None:
        self._subscriber = subscriber

    def publish(self, order: ChannelOrder) -> ChannelEvent:
        event = ChannelEvent("evt-" + uuid4().hex, order)
        if not self.drop and self._subscriber is not None:
            try:
                self._subscriber(event)
            except Exception as error:  # the channel sees a failed delivery; it does not crash
                self.errors.append(error)
        return event
