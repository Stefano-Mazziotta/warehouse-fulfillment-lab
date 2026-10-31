from contextlib import contextmanager

import pytest

from inventory.domain import InventoryBalance, InventoryKey
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder


class MemoryTransaction:
    def __init__(self, quantity=3):
        self.order = Order(OrderKey('o', 'order'), 'w', (
            OrderLine('b', 'sku', 2), OrderLine('a', 'sku', 1)))
        self.stock = InventoryBalance(InventoryKey('o', 'sku', 'w', 'l'), quantity)
        self.reservations = []

    def get_order(self, key, *, lock=False):
        return self.order

    def lock_stock(self, order):
        return [self.stock]

    def save_stock(self, balance):
        self.stock = balance

    def add_reservation(self, reservation):
        self.reservations.append(reservation)

    def get_reservations(self, key):
        return tuple(self.reservations)

    def save_order(self, order):
        self.order = order

    @contextmanager
    def __call__(self):
        yield self


def test_duplicate_sku_demand_distributed_by_line_and_retry_noop():
    tx = MemoryTransaction()
    allocate = AllocateOrder(tx)
    assert allocate.execute(tx.order.key).status == OrderStatus.ALLOCATED
    assert [r.quantity for r in tx.reservations] == [1, 2]
    allocate.execute(tx.order.key)
    assert tx.stock.allocated == 3
    assert len(tx.reservations) == 2
    cancel = CancelOrder(tx)
    assert cancel.execute(tx.order.key).status == OrderStatus.CANCELLED
    cancel.execute(tx.order.key)
    assert tx.stock.allocated == 0
    assert len(tx.reservations) == 2
    with pytest.raises(OrderError):
        allocate.execute(tx.order.key)


def test_shortage_checks_aggregate_before_any_write():
    tx = MemoryTransaction(quantity=2)
    with pytest.raises(OrderError):
        AllocateOrder(tx).execute(tx.order.key)
    assert tx.stock.allocated == 0
    assert tx.reservations == []
    assert tx.order.status == OrderStatus.CREATED
