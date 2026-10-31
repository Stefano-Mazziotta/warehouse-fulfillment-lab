from dataclasses import dataclass
from typing import Protocol

from orders.domain import OrderStatus


@dataclass(frozen=True)
class OrderProjectionUpdate:
    """What one fulfillment event says about an order, already translated for the read model.

    `stage` is the position of the status in the order lifecycle. The events carry no version
    or sequence number, so the lifecycle order is the only version there is; see
    `ProjectOrderEvent`. The optional facts never change once known, so every update may
    contribute them whatever its stage.
    """

    client_id: str
    order_id: str
    event_id: str
    status: OrderStatus
    stage: int
    warehouse_id: str | None = None
    line_count: int | None = None
    package_count: int | None = None
    tracking_number: str | None = None


@dataclass(frozen=True)
class ProjectedOrder:
    order_id: str
    status: OrderStatus
    warehouse_id: str | None
    line_count: int | None
    package_count: int | None
    tracking_number: str | None


class OrderProjection(Protocol):
    """A rebuildable read model of orders. It answers questions; it never authorizes anything.

    PostgreSQL stays the source of truth: nothing that allocates, picks, packs or ships may
    read this. Every method may raise ProjectionUnavailable.
    """

    def apply(self, change: OrderProjectionUpdate) -> bool:
        """Fold one update in. True when it advanced the status; False for a duplicate or stale one."""

    def get(self, client_id: str, order_id: str) -> ProjectedOrder | None: ...

    def list_for_client(self, client_id: str) -> tuple[ProjectedOrder, ...]: ...

    def reset(self) -> None:
        """Forget every order so the projection can be rebuilt from scratch."""
