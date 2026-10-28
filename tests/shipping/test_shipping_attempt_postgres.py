"""The attempt storage on its own, before any orchestration touches it."""
from dataclasses import replace

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from orders.domain import Order, OrderKey, OrderLine
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_attempt import ShippingAttempt
from shipping.infrastructure.shipping_schema import shipping_attempt_packages, shipping_attempts
from shipping_support import KEY, attempt_rows, prepare_packed

OTHER = OrderKey("other-owner", "order")


def open_attempt(engine):
    with PostgresOrderTransaction(engine) as transaction:
        return ShippingAttempt.open(KEY, transaction.get_packages(KEY))


def store(engine, attempt):
    with PostgresOrderTransaction(engine) as transaction:
        transaction.get_order(attempt.order_key, lock=True)
        transaction.create_attempt(attempt)


def load(engine, key=KEY):
    with PostgresOrderTransaction(engine) as transaction:
        return transaction.get_attempt(key)


def test_missing_attempt_reads_as_none(orders_database):
    prepare_packed(orders_database)
    assert load(orders_database) is None


def test_attempt_round_trips_with_its_packages(orders_database):
    prepare_packed(orders_database)
    attempt = open_attempt(orders_database)
    store(orders_database, attempt)
    assert load(orders_database) == attempt
    assert len(attempt.packages) > 1  # a multi-package payload, not a degenerate one


def test_status_and_tracking_updates_round_trip(orders_database):
    prepare_packed(orders_database)
    attempt = open_attempt(orders_database)
    store(orders_database, attempt)
    receipt = CarrierReceipt(KEY, attempt.attempt_id, attempt.package_ids, "TRACK-1")
    for update in (attempt.mark_unknown(), attempt.confirm(receipt)):
        with PostgresOrderTransaction(orders_database) as transaction:
            transaction.get_order(KEY, lock=True)
            transaction.save_attempt(update)
        assert load(orders_database) == update
    assert load(orders_database).tracking_number == "TRACK-1"


def test_an_order_can_have_only_one_attempt(orders_database):
    prepare_packed(orders_database)
    attempt = open_attempt(orders_database)
    store(orders_database, attempt)
    with pytest.raises(IntegrityError):
        store(orders_database, replace(attempt, attempt_id="second-attempt"))
    assert [r.attempt_id for r in attempt_rows(orders_database)] == [attempt.attempt_id]


def test_save_never_rewrites_the_stored_package_payload(orders_database):
    prepare_packed(orders_database)
    attempt = open_attempt(orders_database)
    store(orders_database, attempt)
    fewer_packages = replace(attempt, packages=attempt.packages[:1], status=ShipmentStatus.UNKNOWN)
    with PostgresOrderTransaction(orders_database) as transaction:
        transaction.get_order(KEY, lock=True)
        transaction.save_attempt(fewer_packages)
    stored = load(orders_database)
    assert stored.status == ShipmentStatus.UNKNOWN
    assert stored.packages == attempt.packages


def test_writes_require_the_order_lock(orders_database):
    prepare_packed(orders_database)
    attempt = open_attempt(orders_database)
    with PostgresOrderTransaction(orders_database) as transaction:
        with pytest.raises(RuntimeError, match="locked"):
            transaction.create_attempt(attempt)
        with pytest.raises(RuntimeError, match="locked"):
            transaction.save_attempt(attempt)
    assert load(orders_database) is None


def test_attempts_are_isolated_by_owner(orders_database):
    engine = orders_database
    prepare_packed(engine)
    attempt = open_attempt(engine)
    store(engine, attempt)
    assert load(engine, OTHER) is None
    with PostgresOrderTransaction(engine) as transaction:
        transaction.create_order(Order(OTHER, "warehouse", (OrderLine("one", "sku", 1),)))

    # Another owner's order cannot reuse the attempt ID or borrow this owner's packages.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(shipping_attempts).values(
            client_id=OTHER.client_id, order_id=OTHER.order_id,
            attempt_id=attempt.attempt_id, status="PENDING"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(shipping_attempts).values(
            client_id=OTHER.client_id, order_id=OTHER.order_id,
            attempt_id="other-attempt", status="PENDING"))
        connection.execute(insert(shipping_attempt_packages).values(
            client_id=OTHER.client_id, order_id=OTHER.order_id,
            package_id=attempt.packages[0].package_id))
    assert load(engine, OTHER) is None
    assert load(engine) == attempt
