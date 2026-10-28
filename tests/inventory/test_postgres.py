"""Real PostgreSQL proof; each test owns one randomly named schema only."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, inspect, text, update
from sqlalchemy.exc import IntegrityError

from inventory.application.allocate_inventory import AllocateInventory
from inventory.application.get_inventory import GetInventory
from inventory.application.inventory_not_found import InventoryNotFound
from inventory.domain import InventoryBalance, InventoryError, InventoryKey
from inventory.infrastructure.inventory_schema import inventory_balances
from inventory.infrastructure.postgres_inventory_repository import (
    PostgresInventoryRepository,
)
from inventory.infrastructure.postgres_inventory_transaction import (
    PostgresInventoryTransaction,
)

KEY = InventoryKey("owner", "sku", "warehouse", "bin")


def migrate(engine, revision):
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if revision == "base":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)


@pytest.fixture
def database():
    url = os.environ.get("LAB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set LAB_TEST_DATABASE_URL for real PostgreSQL proofs")
    admin = create_engine(url)
    assert admin.dialect.name == "postgresql", "SQLite is not concurrency proof"
    schema = "lab_test_" + uuid4().hex
    assert schema.startswith("lab_test_") and len(schema) == 41
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=10000"},
    )
    try:
        migrate(engine, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed(engine, key=KEY, quantity=1):
    with engine.begin() as connection:
        connection.execute(
            insert(inventory_balances).values(
                client_id=key.client_id,
                sku=key.sku,
                warehouse_id=key.warehouse_id,
                location_id=key.location_id,
                on_hand=quantity,
                allocated=0,
                picked=0,
                packed=0,
            )
        )


def test_migration_round_trip(database):
    assert "inventory_balances" in inspect(database).get_table_names()
    migrate(database, "base")
    assert "inventory_balances" not in inspect(database).get_table_names()
    migrate(database, "head")
    assert "inventory_balances" in inspect(database).get_table_names()


def test_owner_and_location_isolation(database):
    keys = [
        KEY,
        InventoryKey("other", "sku", "warehouse", "bin"),
        InventoryKey("owner", "sku", "warehouse", "other"),
        InventoryKey("owner", "sku", "other", "bin"),
        InventoryKey("owner", "other", "warehouse", "bin"),
    ]
    for key in keys:
        seed(database, key)
    AllocateInventory(lambda: PostgresInventoryTransaction(database)).execute(KEY, 1)
    reader = GetInventory(PostgresInventoryRepository(database))
    assert [reader.execute(key).allocated for key in keys] == [1, 0, 0, 0, 0]


def test_rollback_after_saved_change(database):
    seed(database)
    with pytest.raises(RuntimeError, match="crash"):
        with PostgresInventoryTransaction(database) as transaction:
            transaction.save(transaction.get_for_update(KEY).allocate(1))
            raise RuntimeError("crash")
    assert PostgresInventoryRepository(database).get(KEY).allocated == 0


def test_database_constraints_protect_non_application_writers(database):
    seed(database)
    for values in ({"allocated": 2}, {"picked": 1}, {"on_hand": -1}, {"packed": -1}):
        with pytest.raises(IntegrityError), database.begin() as connection:
            connection.execute(update(inventory_balances).values(**values))


def test_last_unit_waits_on_lock_then_rechecks_committed_stock(database):
    seed(database)
    # Hold the exact row while the competing application transaction starts.
    with PostgresInventoryTransaction(database) as first:
        first_balance = first.get_for_update(KEY)
        first_pid = first.connection.scalar(text("select pg_backend_pid()"))
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(
            AllocateInventory(lambda: PostgresInventoryTransaction(database)).execute,
            KEY,
            1,
        )
        try:
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with database.connect() as observer:
                    blocked = bool(
                        observer.scalar(
                            text(
                                "select exists(select 1 from pg_stat_activity "
                                "where :pid = any(pg_blocking_pids(pid)))"
                            ),
                            {"pid": first_pid},
                        )
                    )
                if blocked:
                    break
                time.sleep(0.02)
            assert blocked, "second database session never demonstrably waited on first"
            assert not future.done()
            first.save(first_balance.allocate(1))
        except BaseException:
            # Release lock before joining the worker even when the proof fails.
            first.connection.rollback()
            pool.shutdown(wait=True)
            raise
    try:
        with pytest.raises(InventoryError):
            future.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
    assert PostgresInventoryRepository(database).get(KEY).allocated == 1


def test_invalid_and_missing_allocation_leave_database_unchanged(database):
    seed(database)
    allocate = AllocateInventory(lambda: PostgresInventoryTransaction(database))
    with pytest.raises(InventoryError):
        allocate.execute(KEY, 2)
    with pytest.raises(InventoryNotFound):
        allocate.execute(InventoryKey("missing", "sku", "warehouse", "bin"), 1)
    assert PostgresInventoryRepository(database).get(KEY).allocated == 0


def test_save_requires_current_transaction_lock(database):
    seed(database)
    transaction = PostgresInventoryTransaction(database)
    with pytest.raises(RuntimeError, match="locked"):
        transaction.save(InventoryBalance(KEY))
    with transaction:
        with pytest.raises(RuntimeError, match="locked"):
            transaction.save(InventoryBalance(KEY))
