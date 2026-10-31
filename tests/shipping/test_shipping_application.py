"""ShipOrder and ReconcileShipment orchestration against in-memory fakes."""
from dataclasses import replace

import pytest

from in_memory_shipping_transaction import (  # first: it puts tests/packing on sys.path
    InMemoryShippingTransaction, ScriptedCarrier,
)
from in_memory_packing_transaction import BIN_A, BIN_B, KEY, full_packages
from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError, OrderKey, OrderStatus
from shipping.application.reconcile_shipment import ReconcileShipment
from shipping.application.ship_order import ShipOrder
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_error import ShippingError

SHIPPED_STOCK = {BIN_A: (0, 0, 0), BIN_B: (0, 0, 0)}


def stock_of(transaction):
    return {key: (b.on_hand, b.allocated, b.picked) for key, b in transaction.stock.items()}


def setup(status=OrderStatus.PACKED, packages=None):
    transaction = InMemoryShippingTransaction(status, packages)
    carrier = ScriptedCarrier(transaction)
    return transaction, carrier, ShipOrder(transaction, carrier), ReconcileShipment(transaction, carrier)


def test_ship_confirms_the_attempt_and_decrements_stock():
    transaction, carrier, ship, _ = setup()
    attempt = ship.execute(KEY)
    assert attempt.status == ShipmentStatus.SHIPPED and attempt.tracking_number == "TRACK-1"
    assert transaction.get_attempt(KEY) == attempt
    assert transaction.order.status == OrderStatus.SHIPPED
    assert stock_of(transaction) == SHIPPED_STOCK
    assert len(carrier.create_attempt_ids) == 1


def test_repeating_ship_finalizes_once_and_leaves_the_carrier_alone():
    transaction, carrier, ship, reconcile = setup()
    first = ship.execute(KEY)
    calls = carrier.calls
    assert ship.execute(KEY) == first
    assert reconcile.execute(KEY) == first
    assert carrier.calls == calls
    assert transaction.stock_saves == 2 and transaction.order_saves == 1


def test_carrier_is_never_called_inside_a_wms_transaction():
    transaction, carrier, ship, _ = setup()
    seen = []
    carrier.on_call = lambda: seen.append(transaction.get_attempt(KEY).status)
    ship.execute(KEY)
    # The attempt was already committed and visible when the carrier was first asked.
    assert seen and set(seen) == {ShipmentStatus.PENDING}


def test_lost_response_returns_an_unknown_attempt_instead_of_raising():
    # Pins the documented contract: the caller inspects the status and retries via reconcile.
    transaction, carrier, ship, _ = setup()
    carrier.lose_next_create_response = True
    attempt = ship.execute(KEY)
    assert attempt.status == ShipmentStatus.UNKNOWN
    assert transaction.get_attempt(KEY) == attempt
    assert transaction.order.status == OrderStatus.PACKED
    assert stock_of(transaction) == {BIN_A: (2, 2, 2), BIN_B: (3, 3, 3)}


def test_unknown_attempt_is_kept_and_resolved_without_a_second_create():
    transaction, carrier, ship, _ = setup()
    carrier.lose_next_create_response = True
    unknown = ship.execute(KEY)
    shipped = ship.execute(KEY)
    assert shipped.attempt_id == unknown.attempt_id
    assert shipped.status == ShipmentStatus.SHIPPED
    assert carrier.create_attempt_ids == [unknown.attempt_id]
    assert len(transaction.attempts) == 1
    assert stock_of(transaction) == SHIPPED_STOCK


def test_not_found_creates_again_with_the_same_attempt_id():
    transaction, carrier, ship, reconcile = setup()
    carrier.drop_next_create = True
    unknown = ship.execute(KEY)
    assert unknown.status == ShipmentStatus.UNKNOWN and carrier.shipments == {}
    shipped = reconcile.execute(KEY)
    assert shipped.status == ShipmentStatus.SHIPPED
    assert carrier.create_attempt_ids == [unknown.attempt_id, unknown.attempt_id]
    assert list(carrier.shipments) == [unknown.attempt_id]


def test_unavailable_lookup_never_creates_and_recovers_later():
    transaction, carrier, ship, reconcile = setup()
    carrier.lookup_unavailable = True
    assert ship.execute(KEY).status == ShipmentStatus.UNKNOWN
    assert carrier.create_attempt_ids == []
    carrier.lookup_unavailable = False
    assert reconcile.execute(KEY).status == ShipmentStatus.SHIPPED
    assert len(carrier.create_attempt_ids) == 1


def test_crash_before_the_carrier_call_keeps_a_pending_attempt_that_recovers():
    transaction, carrier, ship, _ = setup()

    def crash():
        raise RuntimeError("process died")

    carrier.on_call = crash
    with pytest.raises(RuntimeError, match="process died"):
        ship.execute(KEY)
    pending = transaction.get_attempt(KEY)
    assert pending.status == ShipmentStatus.PENDING
    carrier.on_call = None
    recovered = ship.execute(KEY)
    assert recovered.attempt_id == pending.attempt_id
    assert recovered.status == ShipmentStatus.SHIPPED


def test_ship_of_unknown_order_is_typed_absence():
    transaction, carrier, ship, reconcile = setup()
    missing = OrderKey("owner", "missing")
    with pytest.raises(OrderNotFound):
        ship.execute(missing)
    with pytest.raises(OrderNotFound):
        reconcile.execute(missing)
    assert carrier.calls == 0


@pytest.mark.parametrize("status", [
    OrderStatus.CREATED, OrderStatus.ALLOCATED, OrderStatus.PICKING,
    OrderStatus.PICKED, OrderStatus.CANCELLED,
])
def test_only_packed_orders_ship_and_no_attempt_is_created(status):
    transaction, carrier, ship, _ = setup(status)
    with pytest.raises(OrderError, match="PACKED"):
        ship.execute(KEY)
    assert transaction.attempts == {} and carrier.calls == 0


def test_incomplete_packages_are_rejected_before_any_attempt():
    transaction, carrier, ship, _ = setup(packages=full_packages()[:1])
    with pytest.raises(OrderError):
        ship.execute(KEY)
    assert transaction.attempts == {} and carrier.calls == 0


def test_reconcile_without_an_attempt_is_rejected():
    _, carrier, _, reconcile = setup()
    with pytest.raises(ShippingError, match="no shipping attempt"):
        reconcile.execute(KEY)
    assert carrier.calls == 0


@pytest.mark.parametrize("tamper", [
    lambda r: replace(r, package_ids=frozenset(sorted(r.package_ids)[:1])),
    lambda r: replace(r, package_ids=r.package_ids | {"ghost"}),
    lambda r: replace(r, order_key=OrderKey("intruder", "order")),
    lambda r: replace(r, attempt_id="another-attempt"),
])
def test_receipt_for_the_wrong_package_set_owner_or_attempt_is_rejected(tamper):
    transaction, carrier, ship, reconcile = setup()
    carrier.lose_next_create_response = True
    ship.execute(KEY)
    carrier.tamper = tamper
    with pytest.raises(ShippingError):
        reconcile.execute(KEY)
    assert transaction.order.status == OrderStatus.PACKED
    assert stock_of(transaction) == {BIN_A: (2, 2, 2), BIN_B: (3, 3, 3)}
    carrier.tamper = None
    assert reconcile.execute(KEY).status == ShipmentStatus.SHIPPED


def test_order_that_left_packed_cannot_be_finalized_by_a_late_receipt():
    transaction, carrier, ship, reconcile = setup()
    carrier.lose_next_create_response = True
    ship.execute(KEY)
    transaction.set_status(OrderStatus.CANCELLED)
    with pytest.raises(OrderError, match="PACKED"):
        reconcile.execute(KEY)
    assert transaction.get_attempt(KEY).status == ShipmentStatus.UNKNOWN
    assert stock_of(transaction) == {BIN_A: (2, 2, 2), BIN_B: (3, 3, 3)}
