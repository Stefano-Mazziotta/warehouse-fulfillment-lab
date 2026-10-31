"""The read cache end to end: PostgreSQL stays authoritative, Valkey may vanish."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import event

from api.app_config import AppConfig
from api.service_composition import compose_services
from api_support import attach, build_lab, seed_stock
from order_cache_support import FakeOrderSummaryCache
from orders.application.order_summary import OrderSummary
from orders.domain import Order, OrderKey, OrderLine, OrderStatus

CREATE = """mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId } } }"""
ORDER_INPUT = {"orderId": "o1", "warehouseId": "w1", "lines": [
    {"lineId": "l1", "sku": "sku", "quantity": 2}]}
READ = '{ order(orderId: "o1") { status } }'
UNREACHABLE = "valkey://127.0.0.1:1/0"


def cached_lab(engine, url):
    return build_lab(engine, valkey_url=url, cache_key_prefix=f"lab-test:{uuid4().hex}:")


def count_order_selects(engine):
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(connection, cursor, statement, *rest):
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select") and " from orders" in normalized:
            statements.append(statement)

    return statements


def status(lab):
    return lab.ok(READ)["order"]["status"]


def test_second_read_is_served_from_valkey_without_querying_postgres(orders_database, valkey_url):
    lab = cached_lab(orders_database, valkey_url)
    lab.ok(CREATE, {"input": ORDER_INPUT})
    selects = count_order_selects(orders_database)
    assert status(lab) == "CREATED"
    first_read = len(selects)
    assert first_read >= 1
    assert status(lab) == "CREATED"
    assert len(selects) == first_read


def test_mutation_invalidates_so_the_next_read_sees_the_new_state(orders_database, valkey_url):
    lab = cached_lab(orders_database, valkey_url)
    seed_stock(orders_database, "owner", "sku", "w1", a=5)
    lab.ok(CREATE, {"input": ORDER_INPUT})
    assert status(lab) == "CREATED"  # populates the cache
    lab.ok('mutation { allocateInventory(orderId: "o1") { order { status } } }')
    assert status(lab) == "ALLOCATED"


def test_reads_and_mutations_work_with_an_unreachable_valkey(orders_database):
    lab = cached_lab(orders_database, UNREACHABLE)
    seed_stock(orders_database, "owner", "sku", "w1", a=5)
    lab.ok(CREATE, {"input": ORDER_INPUT})
    assert status(lab) == "CREATED"
    lab.ok('mutation { allocateInventory(orderId: "o1") { order { status } } }')
    assert status(lab) == "ALLOCATED"


@pytest.mark.skipif(not os.environ.get("LAB_TEST_VALKEY_DOWN_URL"),
                    reason="set LAB_TEST_VALKEY_DOWN_URL to the real Valkey URL while it is stopped")
def test_reads_work_while_the_real_valkey_service_is_stopped(orders_database):
    lab = cached_lab(orders_database, os.environ["LAB_TEST_VALKEY_DOWN_URL"])
    lab.ok(CREATE, {"input": ORDER_INPUT})
    assert status(lab) == "CREATED"


def test_allocation_never_consults_the_cache(orders_database):
    cache = FakeOrderSummaryCache()
    config = AppConfig(database_url=os.environ["LAB_TEST_DATABASE_URL"])
    services = compose_services(orders_database, config, cache=cache)
    seed_stock(orders_database, "owner", "sku", "w1", a=5)
    key = OrderKey("owner", "o1")
    services.create_order.execute(Order(key, "w1", (OrderLine("l1", "sku", 2),)))
    # A poisoned entry claiming the order is CANCELLED must have no say in the allocation.
    cache.entries[("owner", "o1")] = OrderSummary("o1", "w1", OrderStatus.CANCELLED)
    cache.calls.clear()

    allocated = services.allocate_order.execute(key)

    assert allocated.status is OrderStatus.ALLOCATED
    assert [call[0] for call in cache.calls] == ["invalidate"]
