from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.domain import Order, OrderError, OrderStatus

from .order_transaction import OrderTransaction


class CreateOrder:

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(self, order: Order) -> Order:
        # State transitions are separate operations, not client-supplied fields.
        if order.status != OrderStatus.CREATED:
            raise OrderError("New orders must be CREATED")
        with self._transaction() as transaction:
            return transaction.create_order(order)
