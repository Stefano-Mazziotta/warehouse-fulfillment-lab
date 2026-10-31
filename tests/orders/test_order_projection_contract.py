"""One behavioral contract, proven on the in-memory double and on real DynamoDB Local."""
from uuid import uuid4

import pytest

from orders.application.projection_unavailable import ProjectionUnavailable
from orders.domain import OrderStatus
from orders.infrastructure.dynamodb_order_projection import DynamoDbOrderProjection

from order_projection_support import InMemoryOrderProjection, update


@pytest.fixture(params=["in_memory", "dynamodb"])
def projection(request):
    if request.param == "in_memory":
        yield InMemoryOrderProjection()
        return
    url = request.getfixturevalue("dynamodb_url")
    real = DynamoDbOrderProjection(url, table_name=f"lab_test_{uuid4().hex}")
    real.install()
    try:
        yield real
    finally:
        real.drop()


def test_an_unknown_order_is_absent(projection):
    assert projection.get("owner", "nope") is None


def test_an_event_creates_the_order_summary(projection):
    assert projection.apply(update("ALLOCATED", warehouse_id="w1", line_count=2)) is True
    view = projection.get("owner", "o1")
    assert (view.order_id, view.status, view.warehouse_id, view.line_count) == (
        "o1", OrderStatus.ALLOCATED, "w1", 2)
    assert view.package_count is None and view.tracking_number is None


def test_the_same_event_twice_is_a_no_op(projection):
    first = update("ALLOCATED", warehouse_id="w1", line_count=2)
    assert projection.apply(first) is True
    assert projection.apply(first) is False
    assert projection.get("owner", "o1").status == OrderStatus.ALLOCATED


def test_a_stale_event_never_regresses_the_status(projection):
    projection.apply(update("SHIPPED", package_count=2, tracking_number="trk"))
    assert projection.apply(update("PACKED", package_count=2)) is False
    view = projection.get("owner", "o1")
    assert view.status == OrderStatus.SHIPPED and view.tracking_number == "trk"


def test_a_late_event_still_contributes_its_immutable_facts(projection):
    projection.apply(update("PACKED", package_count=2))
    assert projection.apply(update("ALLOCATED", warehouse_id="w1", line_count=3)) is False
    view = projection.get("owner", "o1")
    assert (view.status, view.warehouse_id, view.line_count, view.package_count) == (
        OrderStatus.PACKED, "w1", 3, 2)


def test_each_owner_only_lists_its_own_orders(projection):
    projection.apply(update("ALLOCATED", order_id="b", warehouse_id="w", line_count=1))
    projection.apply(update("ALLOCATED", order_id="a", warehouse_id="w", line_count=1))
    projection.apply(update("ALLOCATED", client_id="other", order_id="x", warehouse_id="w", line_count=1))
    assert [view.order_id for view in projection.list_for_client("owner")] == ["a", "b"]
    assert projection.get("owner", "x") is None


def test_reset_forgets_everything_and_stays_usable(projection):
    projection.apply(update("ALLOCATED", warehouse_id="w", line_count=1))
    projection.reset()
    assert projection.list_for_client("owner") == ()
    assert projection.apply(update("ALLOCATED", warehouse_id="w", line_count=1)) is True


def test_an_unreachable_store_is_projection_unavailable():
    projection = DynamoDbOrderProjection("http://127.0.0.1:1", timeout_seconds=0.2)
    with pytest.raises(ProjectionUnavailable):
        projection.apply(update("ALLOCATED", warehouse_id="w", line_count=1))
    with pytest.raises(ProjectionUnavailable):
        projection.get("owner", "o1")


def test_a_missing_table_is_projection_unavailable(dynamodb_url):
    projection = DynamoDbOrderProjection(dynamodb_url, table_name=f"lab_test_{uuid4().hex}")
    with pytest.raises(ProjectionUnavailable):
        projection.get("owner", "o1")


def test_a_newer_event_advances_the_status(projection):
    projection.apply(update("ALLOCATED", warehouse_id="w1", line_count=2))
    assert projection.apply(update("PICKED")) is True
    assert projection.apply(update("PACKED", package_count=2)) is True
    assert projection.apply(update("SHIPPED", package_count=2, tracking_number="trk")) is True
    view = projection.get("owner", "o1")
    assert (view.status, view.warehouse_id, view.package_count, view.tracking_number) == (
        OrderStatus.SHIPPED, "w1", 2, "trk")
