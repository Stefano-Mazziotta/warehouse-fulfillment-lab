from typing import Any

from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order import ChannelOrder


class InvalidChannelEvent(ValueError):
    pass


def parse_channel_event(body: Any) -> ChannelEvent:
    """Shape and domain validation of a webhook body; anything unparseable is the sender's fault."""
    if not isinstance(body, dict):
        raise InvalidChannelEvent("Body must be a JSON object")
    event_id = body.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise InvalidChannelEvent("event_id must be a nonempty string")
    payload = body.get("order")
    if not isinstance(payload, dict):
        raise InvalidChannelEvent("order must be a JSON object")
    try:
        return ChannelEvent(event_id, ChannelOrder.from_payload(payload))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise InvalidChannelEvent(f"Invalid order payload: {error}") from error
