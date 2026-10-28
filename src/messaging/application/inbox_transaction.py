from typing import Protocol


class InboxTransaction(Protocol):
    def record_inbox(self, consumer_name: str, message_id: str) -> bool:
        """True the first time this consumer sees the message; False for a duplicate."""
