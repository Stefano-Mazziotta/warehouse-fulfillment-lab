from collections.abc import Callable
from contextlib import AbstractContextManager

from messaging.domain.fulfillment_events import order_packed
from orders.application.order_not_found import OrderNotFound
from orders.domain import Order, OrderKey
from packing.domain.packing_config import PackingConfig

from .packing_transaction import PackingTransaction


class FinishPacking:
    """Move the order only after exact reservation and line conservation."""

    def __init__(self, transaction: Callable[[], AbstractContextManager[PackingTransaction]]) -> None:
        self._transaction = transaction

    def execute(self, key: OrderKey) -> Order:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            packages = transaction.get_packages(key)
            PackingConfig(order, transaction.get_reservations(key), packages).require_complete()
            packed = order.finish_packing()
            if packed is not order:
                transaction.save_order(packed)
                transaction.record_event(order_packed(
                    key.client_id, key.order_id, (p.package_id for p in packages)))
            return packed
