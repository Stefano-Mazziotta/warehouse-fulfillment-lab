"""Translating fulfillment events into the read model: idempotent, order-tolerant, side-effect free."""
from itertools import permutations

import pytest

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.fulfillment_events import (
    order_allocated, order_cancelled, order_packed, order_shipped, picking_completed,
)
from messaging.domain.inbound_message import InboundMessage
from orders.application.project_order_event import ProjectOrderEvent
from orders.application.projection_unavailable import ProjectionUnavailable
from orders.domain import OrderStatus

from order_projection_support import InMemoryOrderProjection, inbound  # noqa: I001  (extends sys.path)
from in_memory_messaging import InMemoryInbox

ALLOCATED = order_allocated("owner", "o1", "w1", [("l1", "sku-a", 2), ("l2", "sku-b", 1)])
PICKED = picking_completed("owner", "o1")
PACKED = order_packed("owner", "o1", ["p2", "p1"])
SHIPPED = order_shipped("owner", "o1", "attempt", "trk-1", ["p1", "p2"])
CANCELLED = order_cancelled("owner", "o1")
STATUS_OF = {"OrderAllocated": OrderStatus.ALLOCATED, "PickingCompleted": OrderStatus.PICKED,
             "OrderPacked": OrderStatus.PACKED, "OrderShipped": OrderStatus.SHIPPED}


def view_of(projection, order_id="o1", client_id="owner"):
    return projection.get(client_id, order_id)


@pytest.mark.parametrize("event, status, facts", [
    (ALLOCATED, OrderStatus.ALLOCATED, ("w1", 2, None, None)),
    (PICKED, OrderStatus.PICKED, (None, None, None, None)),
    (PACKED, OrderStatus.PACKED, (None, None, 2, None)),
    (SHIPPED, OrderStatus.SHIPPED, (None, None, 2, "trk-1")),
    (CANCELLED, OrderStatus.CANCELLED, (None, None, None, None)),
])
def test_each_event_type_projects_its_status_and_facts(event, status, facts):
    projection = InMemoryOrderProjection()
    assert ProjectOrderEvent(projection).project(inbound(event)) is True
    view = view_of(projection)
    assert (view.status, view.warehouse_id, view.line_count, view.package_count, view.tracking_number) == (
        status, facts[0], facts[1], facts[2], facts[3])


def test_a_duplicate_event_is_a_no_op_even_without_the_inbox():
    projection, projector = InMemoryOrderProjection(), None
    projector = ProjectOrderEvent(projection)
    assert projector.project(inbound(PACKED)) is True
    assert projector.project(inbound(PACKED)) is False
    assert view_of(projection).status == OrderStatus.PACKED


def test_the_inbox_stops_a_redelivered_event_before_it_reaches_the_projection():
    projection, inbox = InMemoryOrderProjection(), InMemoryInbox()
    applied = []
    real_apply = projection.apply
    projection.apply = lambda change: applied.append(change.event_id) or real_apply(change)
    consumer = IdempotentConsumer(inbox, "order-projection", ProjectOrderEvent(projection))
    assert consumer.handle(inbound(ALLOCATED)) is True
    assert consumer.handle(inbound(ALLOCATED)) is False
    assert applied == [ALLOCATED.message_id]


@pytest.mark.parametrize("arrival", list(permutations([ALLOCATED, PICKED, PACKED, SHIPPED])))
def test_any_arrival_order_converges_to_the_same_order_summary(arrival):
    projection = InMemoryOrderProjection()
    projector = ProjectOrderEvent(projection)
    lifecycle = [ALLOCATED, PICKED, PACKED, SHIPPED]
    for position, event in enumerate(arrival, start=1):
        projector.project(inbound(event))
        furthest = max(arrival[:position], key=lifecycle.index)
        assert view_of(projection).status == STATUS_OF[furthest.event_type], arrival[:position]
    view = view_of(projection)
    assert (view.status, view.warehouse_id, view.line_count, view.package_count, view.tracking_number) == (
        OrderStatus.SHIPPED, "w1", 2, 2, "trk-1")


def test_cancellation_is_terminal_even_when_the_allocation_event_arrives_late():
    projection = InMemoryOrderProjection()
    projector = ProjectOrderEvent(projection)
    projector.project(inbound(CANCELLED))
    projector.project(inbound(ALLOCATED))
    view = view_of(projection)
    assert (view.status, view.warehouse_id) == (OrderStatus.CANCELLED, "w1")


def test_events_of_one_owner_never_appear_for_another():
    projection = InMemoryOrderProjection()
    ProjectOrderEvent(projection).project(inbound(ALLOCATED))
    assert view_of(projection, client_id="other") is None


def test_an_event_type_the_projection_does_not_know_is_ignored():
    projection = InMemoryOrderProjection()
    unknown = InboundMessage("x:owner:o1", "OrderTeleported", "owner", {"order_id": "o1"})
    assert ProjectOrderEvent(projection).project(unknown) is False
    assert projection.items == {}


def test_a_malformed_payload_fails_loudly_instead_of_projecting_garbage():
    broken = InboundMessage("OrderAllocated:owner:o1", "OrderAllocated", "owner", {"order_id": "o1"})
    with pytest.raises(KeyError):
        ProjectOrderEvent(InMemoryOrderProjection()).project(broken)


def test_a_projection_outage_rolls_the_inbox_back_so_the_redelivery_is_processed():
    projection, inbox = InMemoryOrderProjection(), InMemoryInbox()
    consumer = IdempotentConsumer(inbox, "order-projection", ProjectOrderEvent(projection))
    projection.down = True
    with pytest.raises(ProjectionUnavailable):
        consumer.handle(inbound(ALLOCATED))
    assert inbox.seen == set()

    projection.down = False
    assert consumer.handle(inbound(ALLOCATED)) is True
    assert view_of(projection).status == OrderStatus.ALLOCATED
