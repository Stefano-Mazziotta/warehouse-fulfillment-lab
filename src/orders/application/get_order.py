from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.domain import Order, OrderKey

from .order_not_found import OrderNotFound
from .order_transaction import OrderTransaction


class GetOrder:

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(self, key: OrderKey) -> Order:
        with self._transaction() as transaction:
            order = transaction.get_order(key)
            if order is None:
                raise OrderNotFound(key)
            return order
