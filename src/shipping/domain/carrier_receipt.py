from dataclasses import dataclass

from orders.domain import OrderKey

from .shipping_error import ShippingError


@dataclass(frozen=True)
class CarrierReceipt:
    """One order-level confirmation; there is no per-package partial success."""

    order_key: OrderKey
    attempt_id: str
    package_ids: frozenset[str]
    tracking_number: str

    def __post_init__(self) -> None:
        if not isinstance(self.tracking_number, str) or not self.tracking_number.strip():
            raise ShippingError("Receipt requires a tracking number")
        object.__setattr__(self, "package_ids", frozenset(self.package_ids))
