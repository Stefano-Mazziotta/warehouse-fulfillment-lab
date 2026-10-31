"""Carrier outcomes are uncertain; the WMS must still ship and decrement exactly once."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text, update

from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError, OrderKey, OrderStatus
from orders.infrastructure.order_schema import orders
from packing.application.add_package import AddPackage
from shipping.application.reconcile_shipment import ReconcileShipment
from shipping.application.ship_order import ShipOrder
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_error import ShippingError
from shipping.infrastructure.postgres_fake_carrier import PostgresFakeCarrier
from shipping_support import (
    KEY, attempt_rows, balances, box, carrier_shipments, factory, new_carrier,
    order_status, prepare, prepare_packed, reserved_counts,
)

SHIPPED_BALANCES = [("a", 0, 0, 0, 0), ("b", 0, 0, 0, 0)]
PACKED_BALANCES = [("a", 2, 2, 2, 0), ("b", 3, 3, 3, 0)]


def ship(engine, carrier):
    return ShipOrder(factory(engine), carrier).execute(KEY)


def reconcile(engine, carrier):
    return ReconcileShipment(factory(engine), carrier).execute(KEY)


class Spy:
    """Delegates to the fake carrier while rewriting or observing calls."""

    def __init__(self, carrier, *, on_call=None, receipt=None, crash=None):
        self.carrier, self.on_call, self.receipt, self.crash = carrier, on_call, receipt, crash

    def find_shipment(self, order_key, attempt_id):
        if self.crash:
            raise self.crash
        if self.on_call:
            self.on_call()
        found = self.carrier.find_shipment(order_key, attempt_id)
        return found if self.receipt is None or found is None else self.receipt(found)

    def create_shipment(self, attempt):
        if self.on_call:
            self.on_call()
        found = self.carrier.create_shipment(attempt)
        return found if self.receipt is None else self.receipt(found)


def test_ship_decrements_stock_once_and_retains_reservation_history(orders_database):
    engine = orders_database
    prepare_packed(engine)
    reservation_history = reserved_counts(engine)
    carrier = new_carrier(engine)
    first = ship(engine, carrier)
    again = ship(engine, carrier)
    assert first == again
    assert first.status == ShipmentStatus.SHIPPED and first.tracking_number
    assert order_status(engine) == OrderStatus.SHIPPED
    assert balances(engine) == SHIPPED_BALANCES
    assert reserved_counts(engine) == reservation_history
    assert len(carrier_shipments(engine)) == len(attempt_rows(engine)) == 1
    assert reconcile(engine, carrier) == first
    assert balances(engine) == SHIPPED_BALANCES


def test_concurrent_ship_creates_one_attempt_one_shipment_one_decrement(orders_database):
    engine = orders_database
    prepare_packed(engine)
    new_carrier(engine)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: ship(engine, PostgresFakeCarrier(engine)), range(6)))
    assert {r.attempt_id for r in results} == {results[0].attempt_id}
    assert all(r.status == ShipmentStatus.SHIPPED for r in results)
    assert len(attempt_rows(engine)) == len(carrier_shipments(engine)) == 1
    assert balances(engine) == SHIPPED_BALANCES


def test_concurrent_reconciliation_of_unknown_finalizes_once(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    carrier.lose_next_create_response = True
    assert ship(engine, carrier).status == ShipmentStatus.UNKNOWN
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: reconcile(engine, PostgresFakeCarrier(engine)), range(6)))
    assert all(r.status == ShipmentStatus.SHIPPED for r in results)
    assert balances(engine) == SHIPPED_BALANCES
    assert len(carrier_shipments(engine)) == 1


def test_lost_response_leaves_unknown_then_reconciles_without_second_shipment(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    carrier.lose_next_create_response = True
    unknown = ship(engine, carrier)
    assert unknown.status == ShipmentStatus.UNKNOWN
    assert order_status(engine) == OrderStatus.PACKED and balances(engine) == PACKED_BALANCES
    assert len(carrier_shipments(engine)) == 1
    creates_before = carrier.create_calls
    shipped = ship(engine, carrier)
    assert shipped.attempt_id == unknown.attempt_id and shipped.status == ShipmentStatus.SHIPPED
    assert carrier.create_calls == creates_before
    assert len(attempt_rows(engine)) == len(carrier_shipments(engine)) == 1
    assert balances(engine) == SHIPPED_BALANCES


def test_not_found_recreates_with_the_same_attempt_id(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    carrier.drop_next_create = True
    unknown = ship(engine, carrier)
    assert unknown.status == ShipmentStatus.UNKNOWN and carrier_shipments(engine) == []
    shipped = reconcile(engine, carrier)
    assert shipped.status == ShipmentStatus.SHIPPED
    (stored,) = carrier_shipments(engine)
    assert stored.attempt_id == unknown.attempt_id == shipped.attempt_id
    assert len(attempt_rows(engine)) == 1 and balances(engine) == SHIPPED_BALANCES


def test_lookup_unavailable_never_creates_and_stays_unknown(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    carrier.lose_next_create_response = True
    ship(engine, carrier)
    carrier.lookup_unavailable = True
    creates = carrier.create_calls
    assert reconcile(engine, carrier).status == ShipmentStatus.UNKNOWN
    assert carrier.create_calls == creates and balances(engine) == PACKED_BALANCES
    carrier.lookup_unavailable = False
    assert reconcile(engine, carrier).status == ShipmentStatus.SHIPPED


def test_crash_before_carrier_call_leaves_committed_attempt_and_recovers(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    with pytest.raises(RuntimeError, match="process died"):
        ship(engine, Spy(carrier, crash=RuntimeError("process died")))
    (row,) = attempt_rows(engine)
    assert row.status == "PENDING" and carrier_shipments(engine) == []
    recovered = ship(engine, carrier)
    assert recovered.attempt_id == row.attempt_id
    assert recovered.status == ShipmentStatus.SHIPPED
    assert len(attempt_rows(engine)) == len(carrier_shipments(engine)) == 1


def test_no_wms_transaction_spans_the_carrier_call(orders_database):
    engine = orders_database
    prepare_packed(engine)
    observed = []

    def probe():
        with engine.connect() as other:
            observed.append(other.scalar(text("select status from shipping_attempts")))
            other.execute(text("set lock_timeout = '200ms'"))
            other.execute(text("select 1 from orders for update nowait"))
            other.rollback()

    assert ship(engine, Spy(new_carrier(engine), on_call=probe)).status == ShipmentStatus.SHIPPED
    assert observed and set(observed) == {"PENDING"}


def test_carrier_restart_keeps_idempotency_and_results(orders_database):
    engine = orders_database
    prepare_packed(engine)
    first = new_carrier(engine)
    first.lose_next_create_response = True
    attempt = ship(engine, first)
    restarted = new_carrier(engine)
    stored = restarted.find_shipment(KEY, attempt.attempt_id)
    assert stored is not None and stored.package_ids == attempt.package_ids
    assert restarted.create_shipment(attempt) == stored
    assert len(carrier_shipments(engine)) == 1
    assert restarted.find_shipment(KEY, "unknown-attempt") is None


def test_carrier_rejects_same_attempt_id_with_a_different_payload(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    attempt = ship(engine, carrier)
    with pytest.raises(ShippingError):
        carrier.create_shipment(replace(attempt, packages=attempt.packages[:1]))


@pytest.mark.parametrize("tamper", [
    lambda r: replace(r, package_ids=frozenset(list(r.package_ids)[:1])),
    lambda r: replace(r, package_ids=r.package_ids | {"ghost"}),
    lambda r: replace(r, order_key=OrderKey("intruder", "order")),
    lambda r: replace(r, order_key=OrderKey("owner", "elsewhere")),
    lambda r: replace(r, attempt_id="another-attempt"),
])
def test_receipt_for_wrong_packages_owner_order_or_attempt_is_rejected(orders_database, tamper):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)
    carrier.lose_next_create_response = True
    ship(engine, carrier)
    with pytest.raises(ShippingError):
        reconcile(engine, Spy(carrier, receipt=tamper))
    assert order_status(engine) == OrderStatus.PACKED and balances(engine) == PACKED_BALANCES
    assert reconcile(engine, carrier).status == ShipmentStatus.SHIPPED


@pytest.mark.parametrize("status", ["CREATED", "ALLOCATED", "PICKING", "CANCELLED"])
def test_non_packed_order_is_rejected_without_attempt_or_carrier_call(orders_database, status):
    engine = orders_database
    prepare(engine, complete=False)
    with engine.begin() as connection:
        connection.execute(update(orders).values(status=status))
    carrier = new_carrier(engine)
    with pytest.raises(OrderError):
        ship(engine, carrier)
    assert attempt_rows(engine) == [] and carrier.create_calls == 0


def test_picked_but_unpacked_order_is_rejected(orders_database):
    engine = orders_database
    reservation_rows = prepare(engine)
    AddPackage(factory(engine)).execute(box(reservation_rows[0], package_id="partial"))
    carrier = new_carrier(engine)
    with pytest.raises(OrderError):
        ship(engine, carrier)
    assert attempt_rows(engine) == [] and carrier.create_calls == 0


def test_missing_order_is_typed_absence(orders_database):
    carrier = new_carrier(orders_database)
    with pytest.raises(OrderNotFound):
        ship(orders_database, carrier)
    with pytest.raises(OrderNotFound):
        reconcile(orders_database, carrier)


def test_reconcile_without_attempt_is_rejected(orders_database):
    engine = orders_database
    prepare_packed(engine)
    with pytest.raises(ShippingError):
        reconcile(engine, new_carrier(engine))


def test_finalization_fault_rolls_back_stock_order_and_attempt_then_retry_succeeds(orders_database):
    engine = orders_database
    prepare_packed(engine)
    carrier = new_carrier(engine)

    def crash(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE orders"):
            raise RuntimeError("finalization fault")

    event.listen(engine, "after_cursor_execute", crash)
    try:
        with pytest.raises(RuntimeError, match="finalization fault"):
            ship(engine, carrier)
    finally:
        event.remove(engine, "after_cursor_execute", crash)
    assert balances(engine) == PACKED_BALANCES and order_status(engine) == OrderStatus.PACKED
    assert [r.status for r in attempt_rows(engine)] == ["PENDING"]
    assert len(carrier_shipments(engine)) == 1
    assert ship(engine, carrier).status == ShipmentStatus.SHIPPED
    assert balances(engine) == SHIPPED_BALANCES and len(carrier_shipments(engine)) == 1


def test_migration_roundtrip_keeps_attempts_and_refuses_information_loss(orders_database, drain_messaging):
    engine = orders_database
    prepare_packed(engine)
    config = Config("alembic.ini")
    drain_messaging(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_packing")
        command.upgrade(config, "head")
    carrier = new_carrier(engine)
    carrier.lose_next_create_response = True
    ship(engine, carrier)
    drain_messaging(engine)
    with pytest.raises(RuntimeError, match="discard shipping"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0004_packing")
    assert [r.status for r in attempt_rows(engine)] == ["UNKNOWN"]
