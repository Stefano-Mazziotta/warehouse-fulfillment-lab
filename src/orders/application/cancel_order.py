"""Release only this order's unpicked reservations; retain historical rows."""

from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager

from inventory.domain import InventoryKey
from orders.domain import Order, OrderError, OrderKey, OrderStatus

from .order_not_found import OrderNotFound
from .order_transaction import OrderTransaction


class CancelOrder:

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(self, key: OrderKey) -> Order:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            cancelled = order.cancel()
            if cancelled is order:
                return order
            if order.status == OrderStatus.ALLOCATED:
                balances = transaction.lock_stock(order)
                released: Counter[InventoryKey] = Counter()
                for reservation in transaction.get_reservations(key):
                    released[reservation.stock_key] += reservation.quantity
                for balance in balances:
                    quantity = released.pop(balance.key, 0)
                    if quantity:
                        transaction.save_stock(balance.release(quantity))
                if released:
                    raise OrderError("Reservation stock is missing")
            transaction.save_order(cancelled)
            return cancelled
