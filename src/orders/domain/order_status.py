from enum import StrEnum


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    ALLOCATED = "ALLOCATED"
    CANCELLED = "CANCELLED"
