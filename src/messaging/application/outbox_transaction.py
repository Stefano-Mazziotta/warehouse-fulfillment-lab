from datetime import datetime
from typing import Protocol

from messaging.domain.outbox_message import OutboxMessage


class OutboxTransaction(Protocol):
    def claim_due(self, now: datetime, limit: int) -> list[OutboxMessage]:
        """Lock due PENDING rows so a concurrent relay cannot claim the same ones."""

    def save(self, message: OutboxMessage) -> None: ...
