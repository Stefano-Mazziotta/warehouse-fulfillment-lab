from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    """What a consumer receives; message_id is the outbox message_id carried by the broker."""

    message_id: str
    event_type: str
    client_id: str
    payload: Mapping[str, Any]
