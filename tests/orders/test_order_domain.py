from dataclasses import FrozenInstanceError

import pytest

from inventory.domain import InventoryBalance, InventoryError, InventoryKey
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus


def test_order_canonical_immutable_lines():
    order = Order(OrderKey('owner', 'order'), 'warehouse', (
        OrderLine('b', 'sku', 1), OrderLine('a', 'sku', 2)))
    assert [line.line_id for line in order.lines] == ['a', 'b']
    assert order.status == OrderStatus.CREATED
    with pytest.raises(FrozenInstanceError):
        order.warehouse_id = 'other'


@pytest.mark.parametrize('quantity', [0, -1, True, 1.5, '1'])
def test_line_quantity(quantity):
    with pytest.raises(OrderError):
        OrderLine('line', 'sku', quantity)


def test_duplicate_lines_and_empty_order_rejected():
    key = OrderKey('owner', 'order')
    with pytest.raises(OrderError):
        Order(key, 'warehouse', ())
    with pytest.raises(OrderError):
        Order(key, 'warehouse', (OrderLine('a', 'sku', 1), OrderLine('a', 'x', 1)))


@pytest.mark.parametrize('quantity', [0, -1, True, 1.5, 3])
def test_release_protects_picked_and_validates_quantity(quantity):
    balance = InventoryBalance(InventoryKey('o', 's', 'w', 'l'), 5, 4, 2)
    with pytest.raises(InventoryError):
        balance.release(quantity)


def test_release_immutable():
    balance = InventoryBalance(InventoryKey('o', 's', 'w', 'l'), 5, 4, 2)
    assert balance.release(2).allocated == 2
    assert balance.allocated == 4


@pytest.mark.parametrize('key', [None, 'owner/order'])
def test_order_requires_owner_scoped_key(key):
    with pytest.raises(OrderError):
        Order(key, 'warehouse', (OrderLine('a', 'sku', 1),))


def test_order_allocation_is_immutable_and_idempotent():
    original = Order(OrderKey('owner', 'order'), 'warehouse', (OrderLine('a', 'sku', 1),))
    allocated = original.allocate()
    assert original.status == OrderStatus.CREATED
    assert allocated.status == OrderStatus.ALLOCATED
    assert allocated.allocate() is allocated
    assert allocated.lines == original.lines


@pytest.mark.parametrize('allocated', [False, True])
def test_order_cancellation_is_immutable_and_idempotent(allocated):
    original = Order(OrderKey('owner', 'order'), 'warehouse', (OrderLine('a', 'sku', 1),))
    if allocated:
        original = original.allocate()
    cancelled = original.cancel()
    assert cancelled.status == OrderStatus.CANCELLED
    assert cancelled.cancel() is cancelled
    assert original.status != OrderStatus.CANCELLED
    with pytest.raises(OrderError):
        cancelled.allocate()
