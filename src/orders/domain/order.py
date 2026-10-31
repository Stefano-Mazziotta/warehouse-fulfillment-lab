from dataclasses import dataclass, replace

from .order_error import OrderError
from .order_key import OrderKey
from .order_line import OrderLine
from .order_status import OrderStatus


@dataclass(frozen=True)
class Order:
    """Immutable order snapshot; lines and warehouse never change after creation."""

    key: OrderKey
    warehouse_id: str
    lines: tuple[OrderLine, ...]
    status: OrderStatus = OrderStatus.CREATED

    def __post_init__(self) -> None:
        if not isinstance(self.key, OrderKey):
            raise OrderError("Order requires an owner-scoped OrderKey")
        if not isinstance(self.warehouse_id, str) or not self.warehouse_id.strip():
            raise OrderError("Warehouse must be a nonempty string")
        lines = tuple(self.lines)
        if not lines or not all(isinstance(line, OrderLine) for line in lines):
            raise OrderError("An order requires valid lines")
        if len({line.line_id for line in lines}) != len(lines):
            raise OrderError("Line IDs must be unique")
        if not isinstance(self.status, OrderStatus):
            raise OrderError("Unknown order status")
        canonical_lines = tuple(sorted(lines, key=lambda line: line.line_id))
        object.__setattr__(self, "lines", canonical_lines)

    def allocate(self) -> "Order":
        """Promise the complete order; repeated allocation is a no-op."""
        if self.status == OrderStatus.ALLOCATED:
            return self
        if self.status != OrderStatus.CREATED:
            raise OrderError("Only CREATED orders can be allocated")
        return replace(self, status=OrderStatus.ALLOCATED)

    def cancel(self) -> "Order":
        """Cancel before picking; repeated cancellation is a no-op."""
        if self.status == OrderStatus.CANCELLED:
            return self
        if self.status not in (OrderStatus.CREATED, OrderStatus.ALLOCATED):
            raise OrderError("Cancellation is only allowed before picking")
        return replace(self, status=OrderStatus.CANCELLED)
