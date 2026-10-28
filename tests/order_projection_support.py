"""Test doubles and builders for the order read-model projection."""
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent / "messaging"))

from messaging.domain.inbound_message import InboundMessage  # noqa: E402
from messaging.domain.integration_event import IntegrationEvent  # noqa: E402
from orders.application.order_projection import OrderProjectionUpdate, ProjectedOrder
from orders.application.projection_unavailable import ProjectionUnavailable
from orders.domain import OrderStatus


def update(stage_status, *, order_id="o1", client_id="owner", event_id=None, **facts):
    stage, status = {
        "ALLOCATED": (1, OrderStatus.ALLOCATED), "PICKED": (2, OrderStatus.PICKED),
        "PACKED": (3, OrderStatus.PACKED), "SHIPPED": (4, OrderStatus.SHIPPED),
        "CANCELLED": (5, OrderStatus.CANCELLED),
    }[stage_status]
    return OrderProjectionUpdate(
        client_id, order_id, event_id or f"{stage_status}:{client_id}:{order_id}", status, stage, **facts)


class InMemoryOrderProjection:
    """Same observable rules as the DynamoDB adapter: facts always land, the stage only advances."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}
        self.down = False

    def _check(self):
        if self.down:
            raise ProjectionUnavailable("connection refused")

    def apply(self, change: OrderProjectionUpdate) -> bool:
        self._check()
        item = self.items.setdefault((change.client_id, change.order_id), {})
        for name in ("warehouse_id", "line_count", "package_count", "tracking_number"):
            if getattr(change, name) is not None:
                item[name] = getattr(change, name)
        if item.get("stage", 0) >= change.stage:
            return False
        item["stage"], item["status"] = change.stage, change.status
        return True

    def get(self, client_id: str, order_id: str) -> ProjectedOrder | None:
        self._check()
        item = self.items.get((client_id, order_id))
        return None if item is None or "stage" not in item else self._view(order_id, item)

    def list_for_client(self, client_id: str) -> tuple[ProjectedOrder, ...]:
        self._check()
        return tuple(self._view(order_id, item) for (owner, order_id), item in sorted(self.items.items())
                     if owner == client_id and "stage" in item)

    def reset(self) -> None:
        self._check()
        self.items.clear()

    @staticmethod
    def _view(order_id, item):
        return ProjectedOrder(
            order_id, item["status"], item.get("warehouse_id"), item.get("line_count"),
            item.get("package_count"), item.get("tracking_number"))


def inbound(event: IntegrationEvent) -> InboundMessage:
    return InboundMessage(event.message_id, event.event_type, event.client_id, event.payload)


class ListEventSource:
    """An in-memory stand-in for the outbox replay."""

    def __init__(self, *events: IntegrationEvent) -> None:
        self.events_in_order = [inbound(event) for event in events]
        self.reads = 0

    def events(self):
        self.reads += 1
        return iter(self.events_in_order)
