from dataclasses import dataclass, replace
from uuid import NAMESPACE_URL, uuid5

from inventory.domain import InventoryKey
from orders.domain import OrderKey
from packing.domain.package import Package

from .carrier_receipt import CarrierReceipt
from .shipment_status import ShipmentStatus
from .shipping_error import ShippingError


@dataclass(frozen=True)
class ShippingAttempt:
    """The one carrier-facing identity of an order, fixed before any carrier call."""

    order_key: OrderKey
    attempt_id: str
    packages: tuple[Package, ...]
    status: ShipmentStatus = ShipmentStatus.PENDING
    tracking_number: str | None = None

    def __post_init__(self) -> None:
        packages = tuple(self.packages)
        if not packages or len({p.package_id for p in packages}) != len(packages):
            raise ShippingError("An attempt requires unique, nonempty packages")
        if any(p.order_key != self.order_key for p in packages):
            raise ShippingError("Attempt packages must belong to its order")
        if (self.status == ShipmentStatus.SHIPPED) != (self.tracking_number is not None):
            raise ShippingError("Only a shipped attempt carries a tracking number")
        object.__setattr__(self, "packages", tuple(sorted(packages, key=lambda p: p.package_id)))

    @classmethod
    def open(cls, order_key: OrderKey, packages: tuple[Package, ...]) -> "ShippingAttempt":
        # Deterministic from the order: a crash before the first persist cannot
        # fork the carrier-side identity, because the order has one attempt ever.
        attempt_id = str(uuid5(NAMESPACE_URL, f"shipping-attempt/{order_key.client_id}/{order_key.order_id}"))
        return cls(order_key, attempt_id, tuple(packages))

    @property
    def package_ids(self) -> frozenset[str]:
        return frozenset(p.package_id for p in self.packages)

    def mark_unknown(self) -> "ShippingAttempt":
        if self.status != ShipmentStatus.PENDING:
            return self
        return replace(self, status=ShipmentStatus.UNKNOWN)

    def confirm(self, receipt: CarrierReceipt) -> "ShippingAttempt":
        if (receipt.order_key, receipt.attempt_id, receipt.package_ids) != (
                self.order_key, self.attempt_id, self.package_ids):
            raise ShippingError("Receipt does not match the attempt's owner, order, ID and packages")
        if self.status == ShipmentStatus.SHIPPED:
            if self.tracking_number != receipt.tracking_number:
                raise ShippingError("Attempt already shipped with a different tracking number")
            return self
        return replace(self, status=ShipmentStatus.SHIPPED, tracking_number=receipt.tracking_number)

    def shipped_quantities(self) -> dict[InventoryKey, int]:
        totals: dict[InventoryKey, int] = {}
        for package in self.packages:
            for item in package.contents:
                totals[item.stock_key] = totals.get(item.stock_key, 0) + item.quantity
        return totals
