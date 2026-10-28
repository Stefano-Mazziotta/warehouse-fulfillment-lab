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

from packing.application.finish_packing import FinishPacking
from packing_support import KEY, STOCK, factory, prepare, box, saved, wait_for_block



def test_multiple_packages_exact_conservation_retry_and_inventory_unchanged(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    original = [PostgresInventoryRepository(engine).get(r.stock_key) for r in reservations]
    first = box(reservations[0], 1, "first")
    add = AddPackage(factory(engine))
    assert add.execute(first) == first
    assert add.execute(first) == first
    with pytest.raises(OrderError):
        add.execute(replace(first, weight_grams=101))
    with pytest.raises(OrderError):
        FinishPacking(factory(engine)).execute(KEY)
    add.execute(box(reservations[0], 1, "second"))
    for index, reservation in enumerate(reservations[1:]):
        add.execute(box(reservation, package_id=f"remaining-{index}"))
    finish = FinishPacking(factory(engine))
    assert finish.execute(KEY).status == OrderStatus.PACKED
    assert finish.execute(KEY).status == OrderStatus.PACKED
    assert add.execute(first) == first
    with pytest.raises(OrderError):
        add.execute(replace(first, weight_grams=101))
    with pytest.raises(OrderError):
        add.execute(box(reservations[0], 1, "late"))
    assert original == [PostgresInventoryRepository(engine).get(r.stock_key) for r in reservations]
    assert len(saved(engine)) == 4


def test_canonical_retry_with_multiple_contents(orders_database):
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
    assert FinishPacking(factory(engine)).execute(KEY).status == OrderStatus.PACKED


@pytest.mark.parametrize("status", [OrderStatus.CREATED, OrderStatus.ALLOCATED,
                                    OrderStatus.PICKING, OrderStatus.CANCELLED])
def test_new_package_requires_picked_order(orders_database, status):
    engine = orders_database
    reservations = prepare(engine, complete=False)
    with engine.begin() as connection:
        connection.execute(update(orders).values(status=status.value))
    with pytest.raises(OrderError):
        AddPackage(factory(engine)).execute(box(reservations[0]))
    with pytest.raises(OrderError):
        FinishPacking(factory(engine)).execute(KEY)
    assert saved(engine) == ()


def test_missing_order_and_owner_are_typed_absence(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    other = OrderKey("other", "order")
    payload = box(reservations[0])
    foreign = replace(payload, order_key=other, contents=(
        replace(payload.contents[0], order_key=other,
                stock_key=replace(payload.contents[0].stock_key, client_id="other")),))
    with pytest.raises(OrderNotFound):
        AddPackage(factory(engine)).execute(foreign)
    with pytest.raises(OrderNotFound):
        FinishPacking(factory(engine)).execute(other)
    assert saved(engine) == ()


def test_add_waiting_on_finish_rechecks_state(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    for index, reservation in enumerate(reservations):
        AddPackage(factory(engine)).execute(box(reservation, package_id=str(index)))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with PostgresOrderTransaction(engine) as first:
            first.get_order(KEY, lock=True)
            pid = first.connection.scalar(text("select pg_backend_pid()"))
            future = pool.submit(AddPackage(factory(engine)).execute, box(
                reservations[0],
                1,
                "late",
            ))
            wait_for_block(engine, pid)
            FinishPacking(lambda: nullcontext(first)).execute(KEY)
        with pytest.raises(OrderError):
            future.result(timeout=5)
    assert GetOrder(factory(engine)).execute(KEY).status == OrderStatus.PACKED






def test_finish_failure_after_status_write_rolls_back(orders_database):
    engine = orders_database
    reservations = prepare(engine)
    for index, reservation in enumerate(reservations):
        AddPackage(factory(engine)).execute(box(reservation, package_id=str(index)))
    def crash(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE orders"):
            raise RuntimeError("packing completion fault")
    event.listen(engine, "after_cursor_execute", crash)
    try:
        with pytest.raises(RuntimeError, match="packing completion fault"):
            FinishPacking(factory(engine)).execute(KEY)
    finally:
        event.remove(engine, "after_cursor_execute", crash)
    assert GetOrder(factory(engine)).execute(KEY).status == OrderStatus.PICKED
    assert len(saved(engine)) == len(reservations)
    assert FinishPacking(factory(engine)).execute(KEY).status == OrderStatus.PACKED


