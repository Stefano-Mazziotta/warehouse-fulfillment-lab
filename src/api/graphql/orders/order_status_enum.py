from enum import Enum

import strawberry


@strawberry.enum(name="OrderStatus")
class OrderStatusEnum(Enum):
    """Mirrors the domain lifecycle without exposing the domain enum itself."""

    CREATED = "CREATED"
    ALLOCATED = "ALLOCATED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"
