import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .channel_order_line import ChannelOrderLine
from .integrations_error import IntegrationsError


@dataclass(frozen=True)
class ChannelOrder:
    """An order as the sales channel (the source of truth) reports it.

    `version` is the channel's own counter for this order and only grows. It is the
    ordering signal; `updated_at` is only used to page through changes.
    """

    client_id: str
    channel_order_id: str
    warehouse_id: str
    lines: tuple[ChannelOrderLine, ...]
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.client_id, self.channel_order_id, self.warehouse_id)
        ):
            raise IntegrationsError("Identifiers must be nonempty strings")
        lines = tuple(self.lines)
        if not lines or not all(isinstance(line, ChannelOrderLine) for line in lines):
            raise IntegrationsError("A channel order requires valid lines")
        if len({line.line_id for line in lines}) != len(lines):
            raise IntegrationsError("Line IDs must be unique")
        if type(self.version) is not int or self.version < 1:
            raise IntegrationsError("Version must be a positive integer")
        if self.updated_at.tzinfo is None:
            raise IntegrationsError("updated_at needs a timezone")
        object.__setattr__(self, "lines", tuple(sorted(lines, key=lambda line: line.line_id)))

    def content(self) -> dict[str, Any]:
        """What the warehouse would act on; excludes version and timestamps."""
        return {
            "warehouse_id": self.warehouse_id,
            "lines": [
                {"line_id": line.line_id, "sku": line.sku, "quantity": line.quantity}
                for line in self.lines
            ],
        }

    def fingerprint(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]

    def to_payload(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "channel_order_id": self.channel_order_id,
            "version": self.version,
            "updated_at": self.updated_at.isoformat(),
            **self.content(),
        }

    @staticmethod
    def from_payload(payload: Mapping[str, Any]) -> "ChannelOrder":
        return ChannelOrder(
            payload["client_id"],
            payload["channel_order_id"],
            payload["warehouse_id"],
            tuple(ChannelOrderLine(**line) for line in payload["lines"]),
            payload["version"],
            datetime.fromisoformat(payload["updated_at"]),
        )
