from dataclasses import replace

import pytest

from inventory.domain import InventoryBalance, InventoryError, InventoryKey
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus, Reservation

KEY = OrderKey('owner', 'order')
STOCK = InventoryKey('owner', 'sku', 'warehouse', 'bin')


def allocated():
    return Order(KEY, 'warehouse', (OrderLine('line', 'sku', 3),)).allocate()


def test_start_and_complete_require_real_picking_and_all_reservations():
    original = allocated()
    picking = original.start_picking()
    assert picking.status == OrderStatus.PICKING
    assert picking.start_picking() is picking
    reservation = Reservation(KEY, 'line', STOCK, 3)
    with pytest.raises(OrderError):
        picking.complete_picking((reservation,))
    with pytest.raises(OrderError):
        picking.complete_picking(())
    picked = picking.complete_picking((reservation.record_pick(3),))
    assert picked.status == OrderStatus.PICKED
    assert picked.complete_picking((reservation.record_pick(3),)) is picked
    for order in (picking, picked):
        with pytest.raises(OrderError):
            order.cancel()
    with pytest.raises(OrderError):
        picked.start_picking()
    with pytest.raises(OrderError):
        original.complete_picking((reservation.record_pick(3),))


@pytest.mark.parametrize('target', [0, -1, True, 1.5, '1', 4])
def test_reservation_rejects_invalid_targets(target):
    with pytest.raises(OrderError):
        Reservation(KEY, 'line', STOCK, 3).record_pick(target)


def test_reservation_cumulative_target_is_immutable_retry_safe_and_monotone():
    original = Reservation(KEY, 'line', STOCK, 3)
    partial = original.record_pick(2)
    assert original.picked_quantity == 0
    assert partial.picked_quantity == 2
    assert partial.record_pick(2) is partial
    with pytest.raises(OrderError):
        partial.record_pick(1)


@pytest.mark.parametrize('quantity', [-1, True, 1.5, 4])
def test_reservation_snapshot_bounds(quantity):
    with pytest.raises(OrderError):
        Reservation(KEY, 'line', STOCK, 3, quantity)


@pytest.mark.parametrize('quantity', [0, -1, True, 1.5, 3])
def test_stock_pick_bounds(quantity):
    with pytest.raises(InventoryError):
        InventoryBalance(STOCK, 5, 3, 1).pick(quantity)


def test_stock_pick_changes_only_picked():
    balance = InventoryBalance(STOCK, 5, 3, 1)
    assert balance.pick(2) == replace(balance, picked=3)
    assert balance.picked == 1


@pytest.mark.parametrize("patch", [
    {"order_key": OrderKey("owner", "other")},
    {"line_id": "missing"},
    {"stock_key": InventoryKey("owner", "sku", "other", "bin")},
    {"stock_key": InventoryKey("owner", "other", "warehouse", "bin")},
])
def test_completion_rejects_foreign_or_mismatched_reservations(patch):
    picking = allocated().start_picking()
    reservation = Reservation(KEY, "line", STOCK, 3, 3)
    with pytest.raises(OrderError):
        picking.complete_picking((replace(reservation, **patch),))


def test_completion_rejects_duplicate_reservations():
    reservation = Reservation(KEY, "line", STOCK, 3, 3)
    with pytest.raises(OrderError):
        allocated().start_picking().complete_picking((reservation, reservation))
