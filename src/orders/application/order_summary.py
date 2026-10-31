from dataclasses import dataclass

from orders.domain import OrderStatus


@dataclass(frozen=True)
class OrderSummary:
    """Header-only read model; lines and reservations are loaded in batches on demand."""

    order_id: str
    warehouse_id: str
    status: OrderStatus
