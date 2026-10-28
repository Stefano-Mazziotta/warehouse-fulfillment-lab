import strawberry

from shipping.application.attempt_summary import AttemptSummary

from .shipment_status_enum import ShipmentStatusEnum


@strawberry.type(name="ShipmentAttempt", description=(
    "UNKNOWN means the carrier did not answer; run reconcileShipment to settle it."))
class ShipmentAttemptType:

    attempt_id: str
    status: ShipmentStatusEnum
    tracking_number: str | None
    package_ids: list[str]

    @classmethod
    def from_summary(cls, summary: AttemptSummary) -> "ShipmentAttemptType":
        return cls(
            attempt_id=summary.attempt_id, status=ShipmentStatusEnum(summary.status.value),
            tracking_number=summary.tracking_number, package_ids=list(summary.package_ids))
