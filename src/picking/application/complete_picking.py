from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.application.order_not_found import OrderNotFound
from orders.application.order_transaction import OrderTransaction
from orders.domain import Order, OrderKey


class CompletePicking:

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(self, key: OrderKey) -> Order:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            picked = order.complete_picking(transaction.get_reservations(key))
            if picked is not order:
                transaction.save_order(picked)
            return picked
