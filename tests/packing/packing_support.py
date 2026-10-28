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

KEY = OrderKey("owner", "order")
STOCK = InventoryKey("owner", "sku", "warehouse", "a")

def factory(engine):
    return lambda: PostgresOrderTransaction(engine)


def prepare(engine, *, complete=True):
    # Duplicate SKU lines span source bins: SKU-only totals cannot prove ownership.
    with engine.begin() as connection:
        for location, quantity in (("a", 2), ("b", 3)):
            connection.execute(insert(inventory_balances).values(
                client_id="owner",
                sku="sku",
                warehouse_id="warehouse",
                location_id=location,
                on_hand=quantity,
                allocated=0,
                picked=0,
                packed=0,
            ))
    CreateOrder(factory(engine)).execute(Order(KEY, "warehouse", (
        OrderLine("one", "sku", 3), OrderLine("two", "sku", 2))))
    AllocateOrder(factory(engine)).execute(KEY)
    if complete:
        StartPicking(factory(engine)).execute(KEY)
        with PostgresOrderTransaction(engine) as transaction:
            reservations = transaction.get_reservations(KEY)
        for reservation in reservations:
            RecordPick(factory(engine)).execute(
                KEY,
                reservation.line_id,
                reservation.stock_key,
                reservation.quantity,
            )
        CompletePicking(factory(engine)).execute(KEY)
    with PostgresOrderTransaction(engine) as transaction:
        return transaction.get_reservations(KEY)


def box(reservation, quantity=None, package_id="box"):
    return Package(KEY, package_id, 100, 200, 150, 100, (
        PackageItem(KEY, reservation.line_id, reservation.stock_key,
                    reservation.quantity if quantity is None else quantity),))


def saved(engine):
    with PostgresOrderTransaction(engine) as transaction:
        return transaction.get_packages(KEY)


def wait_for_block(engine, blocker):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.scalar(text("select exists(select 1 from pg_stat_activity "
                                      "where :pid = any(pg_blocking_pids(pid)))"), {"pid": blocker}):
                return
        time.sleep(0.02)
    pytest.fail("Competing PostgreSQL writer never demonstrably blocked")


