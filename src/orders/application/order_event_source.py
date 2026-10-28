from collections.abc import Iterator
from typing import Protocol

from messaging.domain.inbound_message import InboundMessage


class OrderEventSource(Protocol):
    def events(self) -> Iterator[InboundMessage]:
        """Every order event ever recorded, oldest first. Read-only: it must never change the source."""
