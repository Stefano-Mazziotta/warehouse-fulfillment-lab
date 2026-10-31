"""Order-owned picks exercised against disposable real PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from inventory.domain import InventoryKey
from inventory.infrastructure.inventory_schema import inventory_balances
from inventory.infrastructure.postgres_inventory_repository import PostgresInventoryRepository
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder
from orders.application.create_order import CreateOrder
from orders.application.get_order import GetOrder
from orders.application.order_not_found import OrderNotFound
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus
from orders.infrastructure.order_schema import reservations
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction
from picking.application.start_picking import StartPicking
from picking.application.record_pick import RecordPick
from picking.application.complete_picking import CompletePicking

KEY = OrderKey("owner", "order")
STOCK = InventoryKey("owner", "sku", "warehouse", "bin")


def factory(engine):
    return lambda: PostgresOrderTransaction(engine)


def prepared(engine):
    with engine.begin() as connection:
        connection.execute(insert(inventory_balances).values(
            client_id=STOCK.client_id, sku=STOCK.sku, warehouse_id=STOCK.warehouse_id,
            location_id=STOCK.location_id, on_hand=10, allocated=0, picked=0, packed=0))
    CreateOrder(factory(engine)).execute(Order(KEY, "warehouse", (
        OrderLine("a", "sku", 3), OrderLine("b", "sku", 2))))
    AllocateOrder(factory(engine)).execute(KEY)


def records(engine):
    with PostgresOrderTransaction(engine) as transaction:
        return transaction.get_reservations(KEY)


def test_partial_retry_completion_and_cancel_cutoff(orders_database):
    engine = orders_database
    prepared(engine)
    start = StartPicking(factory(engine))
    assert start.execute(KEY).status == OrderStatus.PICKING
    assert start.execute(KEY).status == OrderStatus.PICKING
    pick = RecordPick(factory(engine))
    assert pick.execute(KEY, "a", STOCK, 1).picked_quantity == 1
    assert pick.execute(KEY, "a", STOCK, 1).picked_quantity == 1
    balance = PostgresInventoryRepository(engine).get(STOCK)
    assert (balance.on_hand, balance.allocated, balance.picked, balance.available) == (10, 5, 1, 5)
    for target in (0, True, -1, 4):
        with pytest.raises(OrderError):
            pick.execute(KEY, "a", STOCK, target)
    with pytest.raises(OrderError):
        CompletePicking(factory(engine)).execute(KEY)
    with pytest.raises(OrderError):
        CancelOrder(factory(engine)).execute(KEY)
    pick.execute(KEY, "a", STOCK, 3)
    with pytest.raises(OrderError):
        pick.execute(KEY, "a", STOCK, 2)
    pick.execute(KEY, "b", STOCK, 2)
    complete = CompletePicking(factory(engine))
    assert complete.execute(KEY).status == OrderStatus.PICKED
    assert complete.execute(KEY).status == OrderStatus.PICKED
    for operation in (start, CancelOrder(factory(engine))):
        with pytest.raises(OrderError):
            operation.execute(KEY)
    with pytest.raises(OrderError):
        pick.execute(KEY, "a", STOCK, 3)


@pytest.mark.parametrize("patch", [
    {"client_id": "other"}, {"sku": "other"}, {"warehouse_id": "other"},
    {"location_id": "other"},
])
def test_full_identity_ownership(orders_database, patch):
    from dataclasses import replace
    engine = orders_database
    prepared(engine)
    StartPicking(factory(engine)).execute(KEY)
    with pytest.raises(OrderError):
        RecordPick(factory(engine)).execute(KEY, "a", replace(STOCK, **patch), 1)
    with pytest.raises(OrderError):
        RecordPick(factory(engine)).execute(KEY, "missing", STOCK, 1)
    with pytest.raises(OrderNotFound):
        RecordPick(factory(engine)).execute(OrderKey("other", "order"), "a", STOCK, 1)
    assert all(r.picked_quantity == 0 for r in records(engine))


def test_created_allocated_cancelled_cannot_record_pick(orders_database):
    engine = orders_database
    prepared(engine)
    pick = RecordPick(factory(engine))
    with pytest.raises(OrderError):
        pick.execute(KEY, "a", STOCK, 1)
    CancelOrder(factory(engine)).execute(KEY)
    with pytest.raises(OrderError):
        StartPicking(factory(engine)).execute(KEY)
    with pytest.raises(OrderError):
        pick.execute(KEY, "a", STOCK, 1)


def test_fault_after_balance_write_rolls_back_reservation_and_balance(orders_database):
    engine = orders_database
    prepared(engine)
    StartPicking(factory(engine)).execute(KEY)
    writes = []

    def crash(connection, cursor, statement, parameters, context, many):
        if statement.startswith("UPDATE inventory_balances"):
            writes.append(statement)
            raise RuntimeError("pick fault")
    event.listen(engine, "after_cursor_execute", crash)
    try:
        with pytest.raises(RuntimeError, match="pick fault"):
            RecordPick(factory(engine)).execute(KEY, "a", STOCK, 2)
    finally:
        event.remove(engine, "after_cursor_execute", crash)
    assert writes
    assert PostgresInventoryRepository(engine).get(STOCK).picked == 0
    assert all(r.picked_quantity == 0 for r in records(engine))
    assert GetOrder(factory(engine)).execute(KEY).status == OrderStatus.PICKING


def wait_for_block(engine, blocker):
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.scalar(text(
                "select exists(select 1 from pg_stat_activity "
                "where :pid = any(pg_blocking_pids(pid)))"), {"pid": blocker}):
                return
        time.sleep(0.02)
    pytest.fail("No demonstrably blocked competing PostgreSQL session")


def test_same_reservation_concurrent_retry_applies_delta_once(orders_database):
    engine = orders_database
    prepared(engine)
    StartPicking(factory(engine)).execute(KEY)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with PostgresOrderTransaction(engine) as first:
            first.get_order(KEY, lock=True)
            pid = first.connection.scalar(text("select pg_backend_pid()"))
            future = pool.submit(RecordPick(factory(engine)).execute, KEY, "a", STOCK, 2)
            wait_for_block(engine, pid)
            RecordPick(lambda: nullcontext(first)).execute(KEY, "a", STOCK, 2)
        assert future.result(timeout=5).picked_quantity == 2
    assert PostgresInventoryRepository(engine).get(STOCK).picked == 2
    assert records(engine)[0].picked_quantity == 2


@pytest.mark.parametrize("winner", ["start", "cancel"])
def test_start_and_cancel_serialize_at_cutoff(orders_database, winner):
    engine = orders_database
    prepared(engine)
    first_operation = StartPicking if winner == "start" else CancelOrder
    second_operation = CancelOrder if winner == "start" else StartPicking
    with ThreadPoolExecutor(max_workers=1) as pool:
        with PostgresOrderTransaction(engine) as first:
            first.get_order(KEY, lock=True)
            pid = first.connection.scalar(text("select pg_backend_pid()"))
            future = pool.submit(second_operation(factory(engine)).execute, KEY)
            wait_for_block(engine, pid)
            first_operation(lambda: nullcontext(first)).execute(KEY)
        with pytest.raises(OrderError):
            future.result(timeout=5)
    expected = OrderStatus.PICKING if winner == "start" else OrderStatus.CANCELLED
    assert GetOrder(factory(engine)).execute(KEY).status == expected
    assert PostgresInventoryRepository(engine).get(STOCK).allocated == (5 if winner == "start" else 0)


def test_db_bounds_and_migration_refuses_information_loss(orders_database, drain_messaging):
    engine = orders_database
    prepared(engine)
    for target in (-1, 4):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(update(reservations).where(reservations.c.line_id == "a")
                               .values(picked_quantity=target))
    config = Config("alembic.ini")
    drain_messaging(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002_orders")
        command.upgrade(config, "head")
    assert all(r.picked_quantity == 0 for r in records(engine))
    StartPicking(factory(engine)).execute(KEY)
    for target in (0, 1):
        if target:
            RecordPick(factory(engine)).execute(KEY, "a", STOCK, target)
        drain_messaging(engine)
        with pytest.raises(RuntimeError, match="discard picking"):
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "0002_orders")
    assert records(engine)[0].picked_quantity == 1


@pytest.mark.parametrize("operation", [StartPicking, CompletePicking])
def test_missing_picking_order_is_typed_absence(orders_database, operation):
    with pytest.raises(OrderNotFound):
        operation(factory(orders_database)).execute(KEY)


def test_migration_preserves_existing_zero_progress_and_guards_progress_independently(
        orders_database, drain_messaging):
    engine = orders_database
    prepared(engine)
    config = Config("alembic.ini")
    drain_messaging(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002_orders")
        command.upgrade(config, "head")
    assert [(r.quantity, r.picked_quantity) for r in records(engine)] == [(3, 0), (2, 0)]
    # Even an inconsistent legacy import must not lose its nonzero progress.
    with engine.begin() as connection:
        connection.execute(update(reservations).where(reservations.c.line_id == "a")
                           .values(picked_quantity=1))
    drain_messaging(engine)
    with pytest.raises(RuntimeError, match="discard picking"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0002_orders")
    assert records(engine)[0].picked_quantity == 1


def test_completed_order_also_blocks_migration_downgrade(orders_database, drain_messaging):
    engine = orders_database
    prepared(engine)
    StartPicking(factory(engine)).execute(KEY)
    RecordPick(factory(engine)).execute(KEY, "a", STOCK, 3)
    RecordPick(factory(engine)).execute(KEY, "b", STOCK, 2)
    CompletePicking(factory(engine)).execute(KEY)
    drain_messaging(engine)
    config = Config("alembic.ini")
    with pytest.raises(RuntimeError, match="discard picking"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0002_orders")
