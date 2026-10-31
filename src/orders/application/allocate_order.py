"""Allocate all lines together; no single-balance transaction loop."""

from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.domain import Order, OrderError, OrderKey, Reservation

from .order_not_found import OrderNotFound
from .order_transaction import OrderTransaction


class AllocateOrder:

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(self, key: OrderKey) -> Order:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            allocated = order.allocate()
            if allocated is order:
                return order
            balances = transaction.lock_stock(order)
            demand: Counter[str] = Counter()
            available: Counter[str] = Counter()
            for line in order.lines:
                demand[line.sku] += line.quantity
            for balance in balances:
                available[balance.key.sku] += balance.available
            if any(available[sku] < quantity for sku, quantity in demand.items()):
                raise OrderError("Insufficient stock for complete order")

            # Canonical line IDs and sorted stock identities make selection reproducible.
            for line in order.lines:
                remaining = line.quantity
                for index, balance in enumerate(balances):
                    if balance.key.sku != line.sku or not balance.available:
                        continue
                    quantity = min(remaining, balance.available)
                    if not quantity:
                        break
                    balances[index] = balance.allocate(quantity)
                    transaction.save_stock(balances[index])
                    transaction.add_reservation(
                        Reservation(key, line.line_id, balance.key, quantity)
                    )
                    remaining -= quantity
                    if not remaining:
                        break
            transaction.save_order(allocated)
            return allocated
