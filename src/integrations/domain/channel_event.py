from dataclasses import dataclass
from urllib.parse import quote

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
        # ":" separates the parts, so each identifier is percent-encoded: otherwise
        # ("a:b", "c") and ("a", "b:c") would share an ID and the second order would be
        # dropped as a duplicate forever.
        client, channel_order = (quote(v, safe="") for v in (order.client_id, order.channel_order_id))
        event_id = f"reconcile:{client}:{channel_order}:v{order.version}:{order.fingerprint()}"
        return ChannelEvent(event_id, order)
