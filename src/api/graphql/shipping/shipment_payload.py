import strawberry

from .shipment_attempt_type import ShipmentAttemptType


@strawberry.type(name="ShipmentPayload")
class ShipmentPayload:

    shipment: ShipmentAttemptType
