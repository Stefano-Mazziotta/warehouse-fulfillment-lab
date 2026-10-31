from dataclasses import dataclass

from inventory.domain import InventoryKey

from .order_error import OrderError
from .order_key import OrderKey


@dataclass(frozen=True)
class Reservation:
    """Historical attribution of promised units to one order line and stock key."""

    order_key: OrderKey
    line_id: str
    stock_key: InventoryKey
    quantity: int

    def __post_init__(self) -> None:
        if self.order_key.client_id != self.stock_key.client_id:
            raise OrderError("Reservation owner must match stock owner")
        if not isinstance(self.line_id, str) or not self.line_id.strip():
            raise OrderError("Reservation requires a line ID")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise OrderError("Reservation quantity must be a positive integer")
