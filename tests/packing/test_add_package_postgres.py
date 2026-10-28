"""Packing proofs use isolated schemas in the explicitly configured lab database."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
import time

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from inventory.domain import InventoryKey
from inventory.infrastructure.inventory_schema import inventory_balances
from inventory.infrastructure.postgres_inventory_repository import PostgresInventoryRepository
from orders.application.allocate_order import AllocateOrder
from orders.application.create_order import CreateOrder
from orders.application.get_order import GetOrder
from orders.application.order_not_found import OrderNotFound
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus
from orders.infrastructure.order_schema import orders
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction
from picking.application.start_picking import StartPicking
from picking.application.record_pick import RecordPick
from picking.application.complete_picking import CompletePicking
from packing.application.add_package import AddPackage
from packing.domain.package import Package
from packing.domain.package_item import PackageItem
from packing.infrastructure.packing_schema import packages, package_items

from packing_support import KEY, STOCK, factory, prepare, box, saved, wait_for_block

@pytest.mark.parametrize("change", [
    {"line_id": "missing"}, {"stock_key": replace(STOCK, location_id="missing")},
    {"stock_key": replace(STOCK, sku="other")},
    {"stock_key": replace(STOCK, warehouse_id="other")},
])
def test_foreign_content_and_overpack_rejected_without_writes(orders_database, change):
    engine = orders_database
    reservations = prepare(engine)
    payload = box(reservations[0])
    with pytest.raises(OrderError):
        AddPackage(factory(engine)).execute(replace(payload, contents=(replace(
            payload.contents[0],
            **change,
        ),)))
    with pytest.raises(OrderError):
        AddPackage(factory(engine)).execute(box(
            reservations[0],
            reservations[0].quantity + 1,
        ))
    assert saved(engine) == ()


def test_fault_after_header_insert_rolls_back_everything(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    observed = []
    def crash(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO packages"):
            observed.append(statement)
            raise RuntimeError("package header fault")
    event.listen(engine, "after_cursor_execute", crash)
    try:
        with pytest.raises(RuntimeError, match="package header fault"):
            AddPackage(factory(engine)).execute(box(reservations[0]))
    finally:
        event.remove(engine, "after_cursor_execute", crash)
    assert observed and saved(engine) == ()
    with engine.connect() as connection:
        assert connection.execute(select(package_items)).all() == []
    assert GetOrder(factory(engine)).execute(KEY).status == OrderStatus.PICKED


@pytest.mark.parametrize("same_id", [False, True])
def test_concurrent_packages_serialize_and_recheck_cumulative_quantity(orders_database, same_id):
    engine = orders_database
    reservation = prepare(engine)[0]
    first_box = box(reservation, package_id="first")
    competitor = first_box if same_id else box(reservation, package_id="second")
    with ThreadPoolExecutor(max_workers=1) as pool:
        with PostgresOrderTransaction(engine) as first:
            first.get_order(KEY, lock=True)
            pid = first.connection.scalar(text("select pg_backend_pid()"))
            future = pool.submit(AddPackage(factory(engine)).execute, competitor)
            wait_for_block(engine, pid)
            AddPackage(lambda: nullcontext(first)).execute(first_box)
        if same_id:
            assert future.result(timeout=5) == first_box
        else:
            with pytest.raises(OrderError):
                future.result(timeout=5)
    assert saved(engine) == (first_box,)


def test_adapter_refuses_package_write_without_order_lock(orders_database):
    engine = orders_database
    reservation = prepare(engine)[0]
    with PostgresOrderTransaction(engine) as transaction:
        with pytest.raises(RuntimeError, match="locked"):
            transaction.add_package(box(reservation))
    assert saved(engine) == ()


@pytest.mark.parametrize("field,value", [
    ("weight_grams", 0), ("length_mm", -1), ("width_mm", 0), ("height_mm", 0),
    ("package_id", " "),
])
def test_database_rejects_invalid_package_measurements(orders_database, field, value):
    engine = orders_database
    reservation = prepare(engine)[0]
    AddPackage(factory(engine)).execute(box(reservation))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(update(packages).values(**{field: value}))


@pytest.mark.parametrize("field,value", [
    ("quantity", 0), ("client_id", "other"), ("order_id", "other"),
    ("line_id", "two"), ("warehouse_id", "other"), ("sku", "other"),
    ("location_id", "other"), ("package_id", "other"),
])
def test_database_rejects_foreign_reservation_or_package_content(orders_database, field, value):
    engine = orders_database
    reservation = prepare(engine)[0]
    AddPackage(factory(engine)).execute(box(reservation))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(update(package_items).values(**{field: value}))


def test_concurrent_valid_split_additions_both_persist(orders_database):
    engine = orders_database
    reservation = prepare(engine)[0]
    first_box = box(reservation, 1, "first")
    second_box = box(reservation, 1, "second")
    with ThreadPoolExecutor(max_workers=1) as pool:
        with PostgresOrderTransaction(engine) as first:
            first.get_order(KEY, lock=True)
            pid = first.connection.scalar(text("select pg_backend_pid()"))
            future = pool.submit(AddPackage(factory(engine)).execute, second_box)
            wait_for_block(engine, pid)
            AddPackage(lambda: nullcontext(first)).execute(first_box)
        assert future.result(timeout=5) == second_box
    assert saved(engine) == (first_box, second_box)


def test_canonical_add_retry_with_multiple_contents(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    payload = Package(KEY, "all", 100, 200, 150, 100, tuple(
        PackageItem(KEY, r.line_id, r.stock_key, r.quantity) for r in reservations))
    add = AddPackage(factory(engine))
    assert add.execute(payload) == payload
    assert add.execute(replace(
        payload,
        contents=tuple(reversed(payload.contents)),
    )) == payload


@pytest.mark.parametrize("status", [OrderStatus.CREATED, OrderStatus.ALLOCATED,
                                    OrderStatus.PICKING, OrderStatus.CANCELLED])
def test_add_package_requires_picked_order(orders_database, status):
    engine = orders_database
    reservations = prepare(engine, complete=False)
    with engine.begin() as connection:
        connection.execute(update(orders).values(status=status.value))
    with pytest.raises(OrderError):
        AddPackage(factory(engine)).execute(box(reservations[0]))
    assert saved(engine) == ()


def test_migration_roundtrip_preserves_picked_orders(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0003_picking")
        command.upgrade(config, "head")
    with PostgresOrderTransaction(engine) as transaction:
        assert transaction.get_reservations(KEY) == reservations
        assert transaction.get_order(KEY).status == OrderStatus.PICKED
    assert saved(engine) == ()



@pytest.mark.parametrize("existing", ["package", "packed"])
def test_migration_refuses_information_loss_and_locks_all_tables(orders_database, existing):
    engine = orders_database
    reservations = prepare(engine)
    if existing == "package":
        AddPackage(factory(engine)).execute(box(reservations[0]))
    else:
        # Guard status independently of headers, even for an inconsistent import.
        with engine.begin() as connection:
            connection.execute(update(orders).values(status="PACKED"))
    lock_snapshots = []
    def capture(connection, cursor, statement, parameters, context, many):
        if statement.startswith("LOCK TABLE orders, order_reservations, packages, package_items"):
            lock_snapshots.append(set(connection.execute(text(
                "SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid=l.relation "
                "WHERE l.pid=pg_backend_pid() AND l.mode='AccessExclusiveLock' AND l.granted"
            )).scalars()))
    event.listen(engine, "after_cursor_execute", capture)
    config = Config("alembic.ini")
    try:
        with pytest.raises(RuntimeError, match="discard packing"):
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "0003_picking")
    finally:
        event.remove(engine, "after_cursor_execute", capture)
    assert lock_snapshots and {"orders", "order_reservations", "packages", "package_items"} <= lock_snapshots[0]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005_shipping"
    assert len(saved(engine)) == (1 if existing == "package" else 0)

