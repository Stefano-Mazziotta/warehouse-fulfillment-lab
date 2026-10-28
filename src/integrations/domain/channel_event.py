from dataclasses import dataclass

from .channel_order import ChannelOrder


@dataclass(frozen=True)
class ChannelEvent:
    """A webhook-style notification: an ID the channel chose, plus the order state."""

    event_id: str
    order: ChannelOrder

    @staticmethod
    def for_reconciliation(order: ChannelOrder) -> "ChannelEvent":
        # Deterministic, so re-reading the same state is deduplicated by the inbox. The
        # content fingerprint keeps a same-version-different-content payload from
        # hiding behind an event ID that was already processed.
        event_id = (
            f"reconcile:{order.client_id}:{order.channel_order_id}"
            f":v{order.version}:{order.fingerprint()}"
        )
        return ChannelEvent(event_id, order)
