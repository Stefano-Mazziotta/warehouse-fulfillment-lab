from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError, OrderKey, OrderStatus
from packing.domain.packing_config import PackingConfig
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_attempt import ShippingAttempt
from shipping.domain.shipping_error import ShippingError

from .carrier_port import CarrierPort
from .carrier_unavailable import CarrierUnavailable
from .shipping_transaction import ShippingTransaction


class ReconcileShipment:
    """Settle an open attempt: ask the carrier first, create only on authoritative NOT_FOUND."""

    def __init__(
        self,
        transaction: Callable[[], AbstractContextManager[ShippingTransaction]],
        carrier: CarrierPort,
    ) -> None:
        self._transaction = transaction
        self._carrier = carrier

    def execute(self, key: OrderKey) -> ShippingAttempt:
        with self._transaction() as transaction:
            attempt = transaction.get_attempt(key)
            if attempt is None:
                if transaction.get_order(key) is None:
                    raise OrderNotFound(key)
                raise ShippingError("Order has no shipping attempt")
        if attempt.status == ShipmentStatus.SHIPPED:
            return attempt
        # No WMS transaction is open here. Creation reuses the SAME attempt ID, so a
        # lost response or crashed caller can never become a second shipment.
        try:
            receipt = self._carrier.find_shipment(key, attempt.attempt_id)
            if receipt is None:
                receipt = self._carrier.create_shipment(attempt)
        except CarrierUnavailable:
            return self._mark_unknown(key)
        return self._finalize(key, receipt)

    def _mark_unknown(self, key: OrderKey) -> ShippingAttempt:
        with self._transaction() as transaction:
            transaction.get_order(key, lock=True)
            attempt = transaction.get_attempt(key)
            assert attempt is not None
            unknown = attempt.mark_unknown()
            if unknown is not attempt:
                transaction.save_attempt(unknown)
            return unknown

    def _finalize(self, key: OrderKey, receipt: CarrierReceipt) -> ShippingAttempt:
        with self._transaction() as transaction:
            # Locking order: order first, then stock (sorted), as in every other capability.
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            attempt = transaction.get_attempt(key)
            if attempt is None:
                raise ShippingError("Order has no shipping attempt")
            if attempt.status == ShipmentStatus.SHIPPED:
                return attempt.confirm(receipt)
            shipped_attempt = attempt.confirm(receipt)
            reservations = transaction.get_reservations(key)
            if order.status != OrderStatus.PACKED:
                raise OrderError("Only PACKED orders can be finalized as shipped")
            PackingConfig(order, reservations, attempt.packages).require_complete()
            balances = {b.key: b for b in transaction.lock_stock(order)}
            for stock_key, quantity in sorted(
                attempt.shipped_quantities().items(),
                key=lambda entry: (entry[0].sku, entry[0].location_id),
            ):
                if stock_key not in balances:
                    raise OrderError("Shipped stock is missing")
                transaction.save_stock(balances[stock_key].ship(quantity))
            transaction.save_order(order.ship())
            transaction.save_attempt(shipped_attempt)
            return shipped_attempt
