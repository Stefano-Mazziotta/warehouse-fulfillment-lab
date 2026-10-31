"""Real transactions, relational ownership and competing PostgreSQL sessions."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from inventory.domain import InventoryKey
from inventory.infrastructure.inventory_schema import inventory_balances
from inventory.infrastructure.postgres_inventory_repository import PostgresInventoryRepository
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder
from orders.application.create_order import CreateOrder
from orders.application.get_order import GetOrder
from orders.application.order_not_found import OrderNotFound
from orders.infrastructure.order_schema import orders, order_lines, reservations
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction


KEY = OrderKey('owner', 'order')
STOCK = InventoryKey('owner', 'sku', 'warehouse', 'a')


def order(key=KEY, lines=None, warehouse='warehouse'):
    return Order(key, warehouse, tuple(lines or [OrderLine('a', 'sku', 1)]))


def seed(engine, key=STOCK, quantity=1):
    with engine.begin() as connection:
        connection.execute(insert(inventory_balances).values(
            client_id=key.client_id, sku=key.sku, warehouse_id=key.warehouse_id,
            location_id=key.location_id, on_hand=quantity, allocated=0, picked=0, packed=0))


def factory(engine):
    return lambda: PostgresOrderTransaction(engine)


def read_reservations(engine, key=KEY):
    with PostgresOrderTransaction(engine) as transaction:
        return transaction.get_reservations(key)


def test_create_retry_canonical_payload_and_owner_scoped_read(orders_database):
    engine = orders_database
    create = CreateOrder(factory(engine))
    original = order(lines=[OrderLine('b', 'sku', 2), OrderLine('a', 'sku', 1)])
    assert create.execute(original) == original
    assert create.execute(order(lines=list(reversed(original.lines)))) == original
    with pytest.raises(OrderError, match='payload'):
        create.execute(order())
    with pytest.raises(OrderError, match='payload'):
        create.execute(order(lines=original.lines, warehouse='other'))
    with pytest.raises(OrderNotFound):
        GetOrder(factory(engine)).execute(OrderKey('other', 'order'))
    assert create.execute(order(OrderKey('other', 'order'))).key.client_id == 'other'


def test_duplicate_sku_split_locations_retry_cancel_isolation(orders_database):
    engine = orders_database
    seed(engine, quantity=2)
    second_stock = InventoryKey('owner', 'sku', 'warehouse', 'b')
    seed(engine, second_stock, 3)
    create = CreateOrder(factory(engine))
    original = order(lines=[OrderLine('b', 'sku', 2), OrderLine('a', 'sku', 1)])
    create.execute(original)
    other = order(OrderKey('owner', 'other'))
    create.execute(other)
    allocate = AllocateOrder(factory(engine))
    assert allocate.execute(KEY).status == OrderStatus.ALLOCATED
    records = read_reservations(engine)
    assert [(r.line_id, r.stock_key.location_id, r.quantity) for r in records] == [
        ('a', 'a', 1), ('b', 'a', 1), ('b', 'b', 1)]
    allocate.execute(KEY)
    allocate.execute(other.key)
    assert create.execute(original).status == OrderStatus.ALLOCATED
    cancel = CancelOrder(factory(engine))
    cancel.execute(KEY)
    cancel.execute(KEY)
    assert read_reservations(engine) == records
    assert sum(PostgresInventoryRepository(engine).get(k).allocated
               for k in (STOCK, second_stock)) == 1
    assert GetOrder(factory(engine)).execute(other.key).status == OrderStatus.ALLOCATED
    with pytest.raises(OrderError):
        allocate.execute(KEY)


def test_shortage_and_fault_after_write_rollback_everything(orders_database):
    engine = orders_database
    seed(engine)
    CreateOrder(factory(engine)).execute(order(lines=[
        OrderLine('a', 'sku', 1), OrderLine('b', 'missing', 1)]))
    with pytest.raises(OrderError):
        AllocateOrder(factory(engine)).execute(KEY)
    assert PostgresInventoryRepository(engine).get(STOCK).allocated == 0
    assert read_reservations(engine) == ()

    second = order(OrderKey('owner', 'fault'))
    CreateOrder(factory(engine)).execute(second)
    writes = []

    def crash_after_reservation(connection, cursor, statement, parameters, context, many):
        if statement.startswith('INSERT INTO order_reservations'):
            writes.append(statement)
            raise RuntimeError('fault after reservation write')

    event.listen(engine, 'after_cursor_execute', crash_after_reservation)
    try:
        with pytest.raises(RuntimeError, match='fault'):
            AllocateOrder(factory(engine)).execute(second.key)
    finally:
        event.remove(engine, 'after_cursor_execute', crash_after_reservation)
    assert writes
    assert PostgresInventoryRepository(engine).get(STOCK).allocated == 0
    assert read_reservations(engine, second.key) == ()
    assert GetOrder(factory(engine)).execute(second.key).status == OrderStatus.CREATED


def test_other_owner_or_warehouse_stock_never_satisfies_order(orders_database):
    engine = orders_database
    for key in [InventoryKey('other', 'sku', 'warehouse', 'a'),
                InventoryKey('owner', 'sku', 'other', 'a')]:
        seed(engine, key, 10)
    CreateOrder(factory(engine)).execute(order())
    with pytest.raises(OrderError):
        AllocateOrder(factory(engine)).execute(KEY)
    CancelOrder(factory(engine)).execute(KEY)
    assert GetOrder(factory(engine)).execute(KEY).status == OrderStatus.CANCELLED


def test_migration_roundtrip_and_composite_foreign_keys(orders_database):
    engine = orders_database
    seed(engine)
    CreateOrder(factory(engine)).execute(order())
    for patch in [{'client_id': 'other'}, {'warehouse_id': 'other'}, {'sku': 'other'},
                  {'line_id': 'other'}, {'location_id': 'other'}]:
        values = dict(client_id='owner', order_id='order', warehouse_id='warehouse',
                      line_id='a', sku='sku', location_id='a', quantity=1)
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert(reservations).values(values | patch))
    config = Config('alembic.ini')
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.downgrade(config, '0001_inventory')
    assert 'orders' not in inspect(engine).get_table_names()
    assert 'inventory_balances' in inspect(engine).get_table_names()
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    assert {'orders', 'order_lines', 'order_reservations'} <= set(inspect(engine).get_table_names())


def wait_for_block(engine, blocker):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            if observer.scalar(text('select exists(select 1 from pg_stat_activity '
                                    'where :pid = any(pg_blocking_pids(pid)))'), {'pid': blocker}):
                return
        time.sleep(0.02)
    pytest.fail('competing PostgreSQL session did not demonstrably wait')


@pytest.mark.parametrize('same_order', [True, False])
def test_concurrent_order_lock_or_stock_lock_rechecks_winner(orders_database, same_order):
    engine = orders_database
    seed(engine)
    create = CreateOrder(factory(engine))
    create.execute(order())
    loser_key = KEY if same_order else OrderKey('owner', 'loser')
    if not same_order:
        create.execute(order(loser_key))
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with PostgresOrderTransaction(engine) as first:
            winner = first.get_order(KEY, lock=True)
            first.lock_stock(winner)
            pid = first.connection.scalar(text('select pg_backend_pid()'))
            future = pool.submit(AllocateOrder(factory(engine)).execute, loser_key)
            try:
                wait_for_block(engine, pid)
                assert not future.done()
                # Reuse the held transaction, without nesting a committing transaction.
                from contextlib import nullcontext
                AllocateOrder(lambda: nullcontext(first)).execute(KEY)
            except BaseException:
                first.connection.rollback()
                raise
        if same_order:
            assert future.result(timeout=5).status == OrderStatus.ALLOCATED
        else:
            with pytest.raises(OrderError):
                future.result(timeout=5)
        assert PostgresInventoryRepository(engine).get(STOCK).allocated == 1
        assert len(read_reservations(engine)) == 1
        if not same_order:
            assert read_reservations(engine, loser_key) == ()
            assert GetOrder(factory(engine)).execute(loser_key).status == OrderStatus.CREATED
    finally:
        pool.shutdown(wait=True)


@pytest.mark.parametrize('operation', [GetOrder, AllocateOrder, CancelOrder])
def test_missing_order_is_typed_absence(orders_database, operation):
    with pytest.raises(OrderNotFound):
        operation(factory(orders_database)).execute(KEY)


@pytest.mark.parametrize('status', [OrderStatus.ALLOCATED, OrderStatus.CANCELLED])
def test_create_rejects_non_created_initial_state(orders_database, status):
    from dataclasses import replace
    with pytest.raises(OrderError, match='CREATED'):
        CreateOrder(factory(orders_database)).execute(replace(order(), status=status))
    with pytest.raises(OrderNotFound):
        GetOrder(factory(orders_database)).execute(KEY)


def test_cancellation_fault_rolls_back_stock_and_state(orders_database):
    engine = orders_database
    seed(engine)
    CreateOrder(factory(engine)).execute(order())
    AllocateOrder(factory(engine)).execute(KEY)

    def crash_after_release(connection, cursor, statement, parameters, context, many):
        if statement.startswith('UPDATE inventory_balances'):
            raise RuntimeError('release fault')

    event.listen(engine, 'after_cursor_execute', crash_after_release)
    try:
        with pytest.raises(RuntimeError, match='release fault'):
            CancelOrder(factory(engine)).execute(KEY)
    finally:
        event.remove(engine, 'after_cursor_execute', crash_after_release)
    assert PostgresInventoryRepository(engine).get(STOCK).allocated == 1
    assert GetOrder(factory(engine)).execute(KEY).status == OrderStatus.ALLOCATED
    assert len(read_reservations(engine)) == 1


@pytest.mark.parametrize('conflicting', [False, True])
def test_concurrent_create_waits_then_compares_committed_payload(orders_database, conflicting):
    engine = orders_database
    payload = order(lines=[OrderLine('a', 'sku', 2 if conflicting else 1)])
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with PostgresOrderTransaction(engine) as first:
            first.create_order(order())
            pid = first.connection.scalar(text('select pg_backend_pid()'))
            future = pool.submit(CreateOrder(factory(engine)).execute, payload)
            try:
                wait_for_block(engine, pid)
                assert not future.done()
            except BaseException:
                first.connection.rollback()
                raise
        if conflicting:
            with pytest.raises(OrderError, match='payload'):
                future.result(timeout=5)
        else:
            assert future.result(timeout=5) == order()
        assert GetOrder(factory(engine)).execute(KEY) == order()
    finally:
        pool.shutdown(wait=True)


def test_allocations_lock_all_skus_and_locations_in_canonical_order(orders_database):
    engine = orders_database
    keys = [InventoryKey('owner', sku, 'warehouse', location)
            for sku in ['z', 'a'] for location in ['z', 'a']]
    for key in keys:
        seed(engine, key, 2)
    payload = order(lines=[OrderLine('z', 'a', 3), OrderLine('a', 'z', 3)])
    CreateOrder(factory(engine)).execute(payload)
    statements = []

    def record(connection, cursor, statement, parameters, context, many):
        if 'FROM inventory_balances' in statement:
            statements.append(statement)

    event.listen(engine, 'before_cursor_execute', record)
    try:
        AllocateOrder(factory(engine)).execute(KEY)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert len(statements) == 1
    sql = statements[0]
    assert 'ORDER BY inventory_balances.sku, inventory_balances.location_id FOR UPDATE' in sql
    assert 'SKIP LOCKED' not in sql
    records = read_reservations(engine)
    assert [(r.line_id, r.stock_key.sku, r.stock_key.location_id, r.quantity)
            for r in records] == [('a', 'z', 'a', 2), ('a', 'z', 'z', 1),
                                  ('z', 'a', 'a', 2), ('z', 'a', 'z', 1)]
