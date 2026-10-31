"""The projection is disposable: losing it costs a replay, never data."""
import random

from messaging.domain.fulfillment_events import (
    order_allocated, order_cancelled, order_packed, order_shipped, picking_completed,
)
from orders.application.project_order_event import ProjectOrderEvent
from orders.application.rebuild_order_projection import RebuildOrderProjection
from orders.domain import OrderStatus

from order_projection_support import InMemoryOrderProjection, ListEventSource, inbound, update

HISTORY = [
    order_allocated("owner", "o1", "w1", [("l1", "sku", 2)]),
    order_allocated("owner", "o2", "w1", [("l1", "sku", 1), ("l2", "sku", 1)]),
    order_allocated("other", "o1", "w9", [("l1", "sku", 1)]),
    picking_completed("owner", "o1"),
    order_cancelled("owner", "o2"),
    order_packed("owner", "o1", ["p1", "p2"]),
    order_shipped("owner", "o1", "attempt", "trk-1", ["p1", "p2"]),
]


def snapshot(projection):
    return {owner: projection.list_for_client(owner) for owner in ("owner", "other")}


def live_projection():
    projection, projector = InMemoryOrderProjection(), None
    projector = ProjectOrderEvent(projection)
    for event in HISTORY:
        projector.project(inbound(event))
    return projection


def test_rebuilding_a_lost_projection_reproduces_what_live_consumption_built():
    expected = snapshot(live_projection())
    lost = InMemoryOrderProjection()
    count = RebuildOrderProjection(lost, ListEventSource(*HISTORY)).run()
    assert count == len(HISTORY)
    assert snapshot(lost) == expected
    assert lost.get("owner", "o1").status == OrderStatus.SHIPPED
    assert lost.get("owner", "o2").status == OrderStatus.CANCELLED


def test_rebuild_discards_whatever_the_projection_held_before():
    projection = InMemoryOrderProjection()
    projection.apply(update("SHIPPED", order_id="ghost", package_count=1, tracking_number="x"))
    RebuildOrderProjection(projection, ListEventSource(*HISTORY)).run()
    assert projection.get("owner", "ghost") is None


def test_rebuild_does_not_depend_on_the_replay_order():
    expected = snapshot(live_projection())
    shuffled = list(HISTORY)
    random.Random(7).shuffle(shuffled)
    projection = InMemoryOrderProjection()
    RebuildOrderProjection(projection, ListEventSource(*shuffled)).run()
    assert snapshot(projection) == expected


def test_replaying_over_an_existing_projection_changes_nothing():
    projection = live_projection()
    expected = snapshot(projection)
    projector = ProjectOrderEvent(projection)
    assert not any(projector.project(inbound(event)) for event in HISTORY)
    assert snapshot(projection) == expected


def test_an_empty_history_leaves_an_empty_projection():
    projection = InMemoryOrderProjection()
    projection.apply(update("ALLOCATED", warehouse_id="w", line_count=1))
    assert RebuildOrderProjection(projection, ListEventSource()).run() == 0
    assert snapshot(projection) == {"owner": (), "other": ()}
