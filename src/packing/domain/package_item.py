from dataclasses import dataclass

from inventory.domain import InventoryKey
from orders.domain import OrderError, OrderKey


@dataclass(frozen=True)
class PackageItem:

    order_key: OrderKey
    line_id: str
    stock_key: InventoryKey
    quantity: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.order_key,
            OrderKey,
        ) or not isinstance(
            self.stock_key,
            InventoryKey,
        ):
            raise OrderError("Package content requires complete reservation identity")
        if self.order_key.client_id != self.stock_key.client_id:
            raise OrderError("Package content owner must match stock owner")
        if not isinstance(self.line_id, str) or not self.line_id.strip():
            raise OrderError("Package content requires a line ID")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise OrderError("Package content quantity must be a positive integer")

    @property
    def identity(self) -> tuple[OrderKey, str, InventoryKey]:
        return self.order_key, self.line_id, self.stock_key

    @property
    def sort_key(self) -> tuple[str, ...]:
        return (self.order_key.client_id, self.order_key.order_id, self.line_id,
                self.stock_key.sku, self.stock_key.warehouse_id, self.stock_key.location_id)
