from dataclasses import dataclass, replace

from inventory.domain import InventoryKey

from .order_error import OrderError
from .order_key import OrderKey


@dataclass(frozen=True)
class Reservation:

    order_key: OrderKey
    line_id: str
    stock_key: InventoryKey
    quantity: int
    picked_quantity: int = 0

    def __post_init__(self) -> None:
        if self.order_key.client_id != self.stock_key.client_id:
            raise OrderError("Reservation owner must match stock owner")
        if not isinstance(self.line_id, str) or not self.line_id.strip():
            raise OrderError("Reservation requires a line ID")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise OrderError("Reservation quantity must be a positive integer")
        if type(self.picked_quantity) is not int or not 0 <= self.picked_quantity <= self.quantity:
            raise OrderError("Picked quantity must be an integer within reserved quantity")

    def record_pick(self, target: int) -> "Reservation":
        """Set a cumulative target; retries never add units twice."""
        if type(target) is not int or not 0 < target <= self.quantity:
            raise OrderError("Picked target must be a positive integer within reservation")
        if target < self.picked_quantity:
            raise OrderError("Picked target cannot decrease")
        if target == self.picked_quantity:
            return self
        return replace(self, picked_quantity=target)
