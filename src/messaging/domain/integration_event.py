from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .messaging_error import MessagingError


@dataclass(frozen=True)
class IntegrationEvent:
    """A business fact other systems may react to; the owner is always explicit."""

    client_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        identity = (self.client_id, self.aggregate_type, self.aggregate_id, self.event_type)
        if not all(isinstance(value, str) and value.strip() for value in identity):
            raise MessagingError("Event identity fields must be nonempty strings")

    @property
    def message_id(self) -> str:
        # Each fulfillment fact happens once per aggregate, so the ID is derivable.
        # Consumers dedupe on it and a buggy double-record hits the primary key.
        return f"{self.event_type}:{self.client_id}:{self.aggregate_id}"
