from typing import Protocol

from orders.domain import OrderKey
from packing.application.packing_transaction import PackingTransaction
from shipping.domain.shipping_attempt import ShippingAttempt


class ShippingTransaction(PackingTransaction, Protocol):
    """Attempts share the order's transaction and lock; the carrier is never inside it."""

    def get_attempt(self, key: OrderKey) -> ShippingAttempt | None: ...
    def create_attempt(self, attempt: ShippingAttempt) -> None: ...
    def save_attempt(self, attempt: ShippingAttempt) -> None: ...
