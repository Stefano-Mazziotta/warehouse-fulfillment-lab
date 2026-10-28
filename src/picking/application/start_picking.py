from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.application.order_not_found import OrderNotFound
from orders.application.order_transaction import OrderTransaction
from orders.domain import Order, OrderKey


class StartPicking:
    """Lock the order before crossing its cancellation cutoff."""

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(self, key: OrderKey) -> Order:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            picking = order.start_picking()
            if picking is not order:
                transaction.save_order(picking)
            return picking
