"""The published language of the fulfillment flow, built from primitives only."""

from collections.abc import Iterable

from .integration_event import IntegrationEvent

ORDER = "order"


def order_allocated(
    client_id: str, order_id: str, warehouse_id: str, lines: Iterable[tuple[str, str, int]]
) -> IntegrationEvent:
    return IntegrationEvent(client_id, ORDER, order_id, "OrderAllocated", {
        "order_id": order_id,
        "warehouse_id": warehouse_id,
        "lines": [{"line_id": line_id, "sku": sku, "quantity": quantity}
                  for line_id, sku, quantity in lines],
    })


def order_cancelled(client_id: str, order_id: str) -> IntegrationEvent:
    return IntegrationEvent(client_id, ORDER, order_id, "OrderCancelled", {"order_id": order_id})


def picking_completed(client_id: str, order_id: str) -> IntegrationEvent:
    return IntegrationEvent(client_id, ORDER, order_id, "PickingCompleted", {"order_id": order_id})


def order_packed(client_id: str, order_id: str, package_ids: Iterable[str]) -> IntegrationEvent:
    return IntegrationEvent(client_id, ORDER, order_id, "OrderPacked", {
        "order_id": order_id, "package_ids": sorted(package_ids)})


def order_shipped(
    client_id: str, order_id: str, attempt_id: str, tracking_number: str,
    package_ids: Iterable[str],
) -> IntegrationEvent:
    return IntegrationEvent(client_id, ORDER, order_id, "OrderShipped", {
        "order_id": order_id,
        "attempt_id": attempt_id,
        "tracking_number": tracking_number,
        "package_ids": sorted(package_ids),
    })
