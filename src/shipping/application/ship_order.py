from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError, OrderKey, OrderStatus
from packing.domain.packing_config import PackingConfig
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_attempt import ShippingAttempt

from .carrier_port import CarrierPort
from .reconcile_shipment import ReconcileShipment
from .shipping_transaction import ShippingTransaction


class ShipOrder:
    """Commit the attempt first, then settle it outside any WMS transaction."""

    def __init__(
        self,
        transaction: Callable[[], AbstractContextManager[ShippingTransaction]],
        carrier: CarrierPort,
    ) -> None:
        self._transaction = transaction
        self._reconcile = ReconcileShipment(transaction, carrier)

    def execute(self, key: OrderKey) -> ShippingAttempt:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            attempt = transaction.get_attempt(key)
            if attempt is None:
                if order.status != OrderStatus.PACKED:
                    raise OrderError("Only PACKED orders can ship")
                packages = transaction.get_packages(key)
                PackingConfig(order, transaction.get_reservations(key), packages).require_complete()
                attempt = ShippingAttempt.open(key, packages)
                transaction.create_attempt(attempt)
            elif attempt.status == ShipmentStatus.SHIPPED:
                return attempt
        return self._reconcile.execute(key)
