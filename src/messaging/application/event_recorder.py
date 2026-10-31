from typing import Protocol

from messaging.domain.integration_event import IntegrationEvent


class EventRecorder(Protocol):
    def record_event(self, event: IntegrationEvent) -> None:
        """Persist the event in the caller's transaction so state and event commit together."""
