from dataclasses import dataclass

from shipping.domain.shipment_status import ShipmentStatus


@dataclass(frozen=True)
class AttemptSummary:
    """What a client may see of a shipping attempt; package payloads stay in the packing read side."""

    order_id: str
    attempt_id: str
    status: ShipmentStatus
    tracking_number: str | None
    package_ids: tuple[str, ...]
