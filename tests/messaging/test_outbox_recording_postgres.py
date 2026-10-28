"""State changes and their events commit or roll back together."""
import pytest
from sqlalchemy import insert, select, text

from inventory.infrastructure.inventory_schema import inventory_balances

from messaging_postgres_support import event_types, outbox_rows
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder
from orders.application.create_order import CreateOrder
from orders.domain import Order, OrderKey, OrderLine
from orders.infrastructure.order_schema import orders
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction
from packing.application.finish_packing import FinishPacking
from picking.application.complete_picking import CompletePicking
from shipping.application.ship_order import ShipOrder
from packing_support import KEY, factory, prepare
from shipping_support import new_carrier, prepare_packed



def order_status(engine, key=KEY):
    with engine.connect() as connection:
        return connection.scalar(select(orders.c.status).where(orders.c.order_id == key.order_id))


class FailsAfterRecording(PostgresOrderTransaction):
    def record_event(self, event):
        super().record_event(event)
        raise RuntimeError("crash after the outbox insert, before commit")


def simple_order(engine, key):
    with engine.begin() as connection:
        connection.execute(insert(inventory_balances).values(
            client_id=key.client_id, sku="sku", warehouse_id="warehouse", location_id="a",
            on_hand=5, allocated=0, picked=0, packed=0))
    CreateOrder(factory(engine)).execute(Order(key, "warehouse", (OrderLine("one", "sku", 1),)))


def test_allocation_writes_state_and_event_in_one_transaction(orders_database):
    engine = orders_database
    key = OrderKey("owner", "solo")
    simple_order(engine, key)
    AllocateOrder(factory(engine)).execute(key)
    (row,) = outbox_rows(engine)
    assert (row["message_id"], row["client_id"], row["aggregate_type"], row["aggregate_id"],
            row["event_type"], row["status"], row["attempt_count"]) == (
        "OrderAllocated:owner:solo", "owner", "order", "solo", "OrderAllocated", "PENDING", 0)
    assert row["payload"]["lines"] == [{"line_id": "one", "sku": "sku", "quantity": 1}]
    assert order_status(engine, key) == "ALLOCATED"


def test_rollback_removes_the_event_together_with_the_state_change(orders_database):
    engine = orders_database
    key = OrderKey("owner", "solo")
    simple_order(engine, key)
    with pytest.raises(RuntimeError, match="outbox insert"):
        AllocateOrder(lambda: FailsAfterRecording(engine)).execute(key)
    assert outbox_rows(engine) == []
    assert order_status(engine, key) == "CREATED"
    with engine.connect() as connection:
        assert connection.scalar(text("select sum(allocated) from inventory_balances")) == 0


def test_cancellation_event_and_idempotent_retry(orders_database):
    engine = orders_database
    key = OrderKey("owner", "solo")
    simple_order(engine, key)
    AllocateOrder(factory(engine)).execute(key)
    CancelOrder(factory(engine)).execute(key)
    CancelOrder(factory(engine)).execute(key)
    assert event_types(engine) == ["OrderAllocated", "OrderCancelled"]


def test_retrying_allocation_and_picking_completion_emits_no_duplicates(orders_database):
    engine = orders_database
    prepare(engine, complete=False)
    AllocateOrder(factory(engine)).execute(KEY)
    assert event_types(engine) == ["OrderAllocated"]


def test_retrying_picking_completion_emits_no_duplicate(orders_database):
    engine = orders_database
    prepare(engine)
    CompletePicking(factory(engine)).execute(KEY)
    assert sorted(event_types(engine)) == ["OrderAllocated", "PickingCompleted"]


def test_retrying_packing_and_shipping_emits_each_fact_once(orders_database):
    engine = orders_database
    prepare_packed(engine)
    FinishPacking(factory(engine)).execute(KEY)
    carrier = new_carrier(engine)
    ShipOrder(factory(engine), carrier).execute(KEY)
    ShipOrder(factory(engine), carrier).execute(KEY)
    assert sorted(event_types(engine)) == [
        "OrderAllocated", "OrderPacked", "OrderShipped", "PickingCompleted"]
    shipped = next(r for r in outbox_rows(engine) if r["event_type"] == "OrderShipped")
    assert shipped["payload"]["tracking_number"] and shipped["payload"]["package_ids"]
    assert shipped["message_id"] == "OrderShipped:owner:order"
