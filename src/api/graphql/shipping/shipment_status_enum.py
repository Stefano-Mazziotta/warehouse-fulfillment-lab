from enum import Enum

import strawberry


@strawberry.enum(name="ShipmentStatus")
class ShipmentStatusEnum(Enum):
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    SHIPPED = "SHIPPED"
