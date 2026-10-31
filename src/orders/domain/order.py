from dataclasses import dataclass, replace

from .order_error import OrderError
from .order_key import OrderKey
from .order_line import OrderLine
from .order_status import OrderStatus
from .reservation import Reservation


@dataclass(frozen=True)
class Order:

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
        if self.status == OrderStatus.ALLOCATED:
            return self
        if self.status != OrderStatus.CREATED:
            raise OrderError("Only CREATED orders can be allocated")
        return replace(self, status=OrderStatus.ALLOCATED)

    def cancel(self) -> "Order":
        if self.status == OrderStatus.CANCELLED:
            return self
        if self.status not in (OrderStatus.CREATED, OrderStatus.ALLOCATED):
            raise OrderError("Cancellation is only allowed before picking")
        return replace(self, status=OrderStatus.CANCELLED)

    def start_picking(self) -> "Order":
        if self.status == OrderStatus.PICKING:
            return self
        if self.status != OrderStatus.ALLOCATED:
            raise OrderError("Only ALLOCATED orders can start picking")
        return replace(self, status=OrderStatus.PICKING)

    def require_picking(self) -> None:
        if self.status != OrderStatus.PICKING:
            raise OrderError("Order must be PICKING")

    def complete_picking(self, reservations: tuple[Reservation, ...]) -> "Order":
        if self.status == OrderStatus.PICKED:
            return self
        self.require_picking()
        totals: dict[str, int] = {}
        identities = set()
        lines = {line.line_id: line for line in self.lines}
        for reservation in reservations:
            line = lines.get(reservation.line_id)
            identity = (reservation.line_id, reservation.stock_key)
            if (
                reservation.order_key != self.key
                or reservation.stock_key.warehouse_id != self.warehouse_id
                or line is None
                or reservation.stock_key.sku != line.sku
                or identity in identities
                or reservation.picked_quantity != reservation.quantity
            ):
                raise OrderError("Every owned reservation must be fully picked")
            identities.add(identity)
            totals[reservation.line_id] = totals.get(reservation.line_id, 0) + reservation.quantity
        if totals != {line.line_id: line.quantity for line in self.lines}:
            raise OrderError("Picked reservations must exactly cover every order line")
        return replace(self, status=OrderStatus.PICKED)

    def finish_packing(self) -> "Order":
        """The packing capability validates contents before this state transition."""
        if self.status == OrderStatus.PACKED:
            return self
        if self.status != OrderStatus.PICKED:
            raise OrderError("Only PICKED orders can finish packing")
        return replace(self, status=OrderStatus.PACKED)
