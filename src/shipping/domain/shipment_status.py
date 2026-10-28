from enum import StrEnum


class ShipmentStatus(StrEnum):
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    SHIPPED = "SHIPPED"
