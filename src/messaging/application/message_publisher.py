from typing import Protocol

from messaging.domain.outbox_message import OutboxMessage


class MessagePublisher(Protocol):
    def publish(self, message: OutboxMessage) -> None:
        """Return once the broker accepted the message; raise PublishFailed otherwise."""
