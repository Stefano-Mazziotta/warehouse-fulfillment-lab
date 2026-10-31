from collections.abc import Callable
from contextlib import AbstractContextManager

from inventory.domain import InventoryKey
from orders.application.order_not_found import OrderNotFound
from orders.application.order_transaction import OrderTransaction
from orders.domain import OrderError, OrderKey, Reservation


class RecordPick:
    """Apply a cumulative reservation target and its stock delta atomically."""

    def __init__(
        self, transaction: Callable[[], AbstractContextManager[OrderTransaction]]
    ) -> None:
        self._transaction = transaction

    def execute(
        self, key: OrderKey, line_id: str, stock_key: InventoryKey, target: int
    ) -> Reservation:
        with self._transaction() as transaction:
            order = transaction.get_order(key, lock=True)
            if order is None:
                raise OrderNotFound(key)
            order.require_picking()
            owned = next(
                (
                    reservation
                    for reservation in transaction.get_reservations(key)
                    if reservation.line_id == line_id
                    and reservation.stock_key == stock_key
                ),
                None,
            )
            if owned is None:
                raise OrderError("No owned reservation matches the complete identity")
            picked = owned.record_pick(target)
            if picked is owned:
                return owned
            balances = transaction.lock_stock(order)
            balance = next((item for item in balances if item.key == stock_key), None)
            if balance is None:
                raise OrderError("Reservation stock is missing")
            delta = picked.picked_quantity - owned.picked_quantity
            transaction.save_stock(balance.pick(delta))
            transaction.save_reservation(picked)
            return picked
