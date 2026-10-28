import json
from typing import Any

from messaging.domain.inbound_message import InboundMessage
from messaging.domain.outbox_message import OutboxMessage


def encode(message: OutboxMessage) -> bytes:
    return json.dumps({
        "message_id": message.message_id,
        "event_type": message.event_type,
        "client_id": message.client_id,
        "aggregate_type": message.aggregate_type,
        "aggregate_id": message.aggregate_id,
        "payload": message.payload,
    }).encode()


def decode(body: bytes) -> InboundMessage:
    """Raise ValueError (or KeyError/TypeError) for a body no retry could ever fix."""
    document: dict[str, Any] = json.loads(body)
    return InboundMessage(
        document["message_id"], document["event_type"], document["client_id"], document["payload"])
