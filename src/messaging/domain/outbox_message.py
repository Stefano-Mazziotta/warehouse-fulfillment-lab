from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping

from .integration_event import IntegrationEvent
from .messaging_error import MessagingError
from .outbox_status import OutboxStatus
from .retry_policy import RetryPolicy


@dataclass(frozen=True)
class OutboxMessage:

    message_id: str
    client_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Mapping[str, Any]
    created_at: datetime
    status: OutboxStatus
    attempt_count: int
    next_attempt_at: datetime
    last_error: str | None = None

    @classmethod
    def pending(cls, event: IntegrationEvent, now: datetime) -> "OutboxMessage":
        return cls(event.message_id, event.client_id, event.aggregate_type, event.aggregate_id,
                   event.event_type, dict(event.payload), now, OutboxStatus.PENDING, 0, now)

    def published(self) -> "OutboxMessage":
        self._require_pending()
        return replace(self, status=OutboxStatus.PUBLISHED, last_error=None)

    def failed(self, error: str, now: datetime, policy: RetryPolicy) -> "OutboxMessage":
        self._require_pending()
        attempts = self.attempt_count + 1
        if attempts >= policy.max_attempts:
            return replace(self, status=OutboxStatus.DEAD, attempt_count=attempts, last_error=error)
        return replace(self, attempt_count=attempts, last_error=error,
                       next_attempt_at=now + policy.delay_after(attempts))

    def _require_pending(self) -> None:
        if self.status != OutboxStatus.PENDING:
            raise MessagingError(f"Only PENDING messages can change; this one is {self.status}")
