from dataclasses import FrozenInstanceError, replace

import pytest

from inventory.domain import InventoryBalance, InventoryError, InventoryKey
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus
from packing.domain.package import Package
from packing.domain.package_item import PackageItem
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_attempt import ShippingAttempt
from shipping.domain.shipping_error import ShippingError

KEY = OrderKey("owner", "order")
STOCK_A = InventoryKey("owner", "sku", "warehouse", "a")
STOCK_B = InventoryKey("owner", "sku", "warehouse", "b")


def package(package_id, stock, quantity, line_id="one"):
    return Package(KEY, package_id, 100, 200, 150, 100,
                   (PackageItem(KEY, line_id, stock, quantity),))


def attempt():
    return ShippingAttempt.open(KEY, (package("p2", STOCK_B, 2), package("p1", STOCK_A, 3)))


def receipt_for(opened, **changes):
    values = dict(order_key=KEY, attempt_id=opened.attempt_id,
                  package_ids=frozenset({"p1", "p2"}), tracking_number="TRK-1")
    return CarrierReceipt(**{**values, **changes})


def test_open_attempt_is_stable_pending_and_canonical():
    opened = attempt()
    assert opened.status == ShipmentStatus.PENDING
    assert [p.package_id for p in opened.packages] == ["p1", "p2"]
    assert opened.attempt_id == attempt().attempt_id
    other = OrderKey("owner", "other")
    foreign = Package(other, "p1", 1, 1, 1, 1, (PackageItem(other, "one", STOCK_A, 1),))
    assert ShippingAttempt.open(other, (foreign,)).attempt_id != opened.attempt_id
    with pytest.raises(FrozenInstanceError):
        opened.status = ShipmentStatus.SHIPPED


def test_payload_must_be_nonempty_unique_and_owned():
    for packages in ((), (package("p1", STOCK_A, 1), package("p1", STOCK_B, 1))):
        with pytest.raises(ShippingError):
            ShippingAttempt.open(KEY, packages)
    other = OrderKey("owner", "other")
    foreign = Package(other, "p9", 1, 1, 1, 1, (PackageItem(other, "one", STOCK_A, 1),))
    with pytest.raises(ShippingError):
        ShippingAttempt.open(KEY, (foreign,))


def test_unknown_is_a_non_terminal_state_that_keeps_identity_and_payload():
    opened = attempt()
    unknown = opened.mark_unknown()
    assert unknown.status == ShipmentStatus.UNKNOWN
    assert (unknown.attempt_id, unknown.packages) == (opened.attempt_id, opened.packages)
    assert unknown.mark_unknown() == unknown


def test_confirm_requires_exact_receipt_and_is_idempotent():
    opened = attempt().mark_unknown()
    shipped = opened.confirm(receipt_for(opened))
    assert (shipped.status, shipped.tracking_number) == (ShipmentStatus.SHIPPED, "TRK-1")
    assert shipped.confirm(receipt_for(opened)) == shipped
    assert shipped.mark_unknown() == shipped
    with pytest.raises(ShippingError):
        shipped.confirm(receipt_for(opened, tracking_number="TRK-2"))


@pytest.mark.parametrize("changes", [
    dict(package_ids=frozenset({"p1"})),
    dict(package_ids=frozenset({"p1", "p2", "p3"})),
    dict(order_key=OrderKey("intruder", "order")),
    dict(order_key=OrderKey("owner", "elsewhere")),
    dict(attempt_id="another-attempt"),
])
def test_wrong_receipt_is_rejected(changes):
    opened = attempt()
    with pytest.raises(ShippingError):
        opened.confirm(receipt_for(opened, **changes))


def test_receipt_requires_tracking_number():
    with pytest.raises(ShippingError):
        receipt_for(attempt(), tracking_number=" ")


def test_shipped_attempt_requires_tracking_number():
    with pytest.raises(ShippingError):
        replace(attempt(), status=ShipmentStatus.SHIPPED)
    with pytest.raises(ShippingError):
        replace(attempt(), tracking_number="TRK-1")


def test_shipped_quantities_sum_by_stock_across_packages():
    opened = ShippingAttempt.open(KEY, (
        package("p1", STOCK_A, 3), package("p2", STOCK_A, 1, line_id="two"),
        package("p3", STOCK_B, 2)))
    assert opened.shipped_quantities() == {STOCK_A: 4, STOCK_B: 2}


def test_order_ships_only_from_packed_and_is_idempotent():
    order = Order(KEY, "warehouse", (OrderLine("one", "sku", 1),), OrderStatus.PACKED)
    shipped = order.ship()
    assert shipped.status == OrderStatus.SHIPPED
    assert shipped.ship() is shipped
    for status in (OrderStatus.CREATED, OrderStatus.PICKED, OrderStatus.CANCELLED):
        with pytest.raises(OrderError):
            replace(order, status=status).ship()


def test_balance_ship_consumes_on_hand_allocated_and_picked_only():
    balance = InventoryBalance(STOCK_A, on_hand=5, allocated=3, picked=3, packed=7)
    shipped = balance.ship(3)
    assert (shipped.on_hand, shipped.allocated, shipped.picked, shipped.packed) == (2, 0, 0, 7)
    for quantity in (0, -1, True, 4):
        with pytest.raises(InventoryError):
            balance.ship(quantity)
