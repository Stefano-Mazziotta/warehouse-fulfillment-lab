"""AddPackage and FinishPacking orchestration against an in-memory transaction."""
import pytest

from in_memory_packing_transaction import (
    BIN_A, BIN_B, KEY, InMemoryPackingTransaction, content, full_packages, package,
)
from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError, OrderKey, OrderStatus
from packing.application.add_package import AddPackage
from packing.application.finish_packing import FinishPacking
from packing.domain.package import Package
from packing.domain.package_item import PackageItem


def test_add_package_stores_it_under_the_order_lock():
    transaction = InMemoryPackingTransaction()
    box = package("box-0", content("one", BIN_A, 2))
    assert AddPackage(transaction).execute(box) == box
    assert transaction.get_packages(KEY) == (box,)
    assert transaction.order.status == OrderStatus.PICKED


def test_one_reservation_may_be_split_across_packages():
    transaction = InMemoryPackingTransaction()
    add = AddPackage(transaction)
    add.execute(package("box-0", content("one", BIN_A, 1)))
    add.execute(package("box-1", content("one", BIN_A, 1)))
    assert len(transaction.get_packages(KEY)) == 2


def test_identical_retry_is_a_noop_even_after_packing_finished():
    transaction = InMemoryPackingTransaction()
    first, second = full_packages()
    add = AddPackage(transaction)
    add.execute(first)
    add.execute(second)
    FinishPacking(transaction).execute(KEY)
    assert add.execute(first) == first
    assert transaction.get_packages(KEY) == (first, second)


def test_same_id_with_another_payload_is_rejected_and_nothing_changes():
    transaction = InMemoryPackingTransaction()
    original = package("box-0", content("one", BIN_A, 2))
    add = AddPackage(transaction)
    add.execute(original)
    with pytest.raises(OrderError, match="different payload"):
        add.execute(package("box-0", content("one", BIN_A, 2), weight_grams=999))
    assert transaction.get_packages(KEY) == (original,)


def test_unknown_order_is_typed_absence():
    missing = OrderKey("owner", "missing")
    stray = Package(missing, "box-0", 100, 200, 150, 100,
                    (PackageItem(missing, "one", BIN_A, 1),))
    with pytest.raises(OrderNotFound):
        AddPackage(InMemoryPackingTransaction()).execute(stray)


@pytest.mark.parametrize("status", [
    OrderStatus.CREATED, OrderStatus.ALLOCATED, OrderStatus.PICKING,
    OrderStatus.PACKED, OrderStatus.SHIPPED, OrderStatus.CANCELLED,
])
def test_new_package_requires_a_picked_order(status):
    transaction = InMemoryPackingTransaction(status)
    with pytest.raises(OrderError, match="PICKED"):
        AddPackage(transaction).execute(package("box-0", content("one", BIN_A, 1)))
    assert transaction.get_packages(KEY) == ()


@pytest.mark.parametrize("box", [
    package("big", content("one", BIN_A, 3)),
    package("wrong-bin", content("two", BIN_A, 1)),
    package("wrong-line", content("missing", BIN_A, 1)),
])
def test_contents_beyond_the_picked_reservations_are_rejected(box):
    transaction = InMemoryPackingTransaction()
    with pytest.raises(OrderError):
        AddPackage(transaction).execute(box)
    assert transaction.get_packages(KEY) == ()


def test_cumulative_quantity_across_packages_cannot_exceed_picked():
    transaction = InMemoryPackingTransaction()
    add = AddPackage(transaction)
    add.execute(package("box-0", content("one", BIN_A, 2)))
    with pytest.raises(OrderError, match="exceeds"):
        add.execute(package("box-1", content("one", BIN_A, 1)))
    assert len(transaction.get_packages(KEY)) == 1


def test_finish_packing_moves_a_fully_packed_order_to_packed():
    transaction = InMemoryPackingTransaction(packages=full_packages())
    assert FinishPacking(transaction).execute(KEY).status == OrderStatus.PACKED
    assert transaction.order.status == OrderStatus.PACKED


def test_finish_packing_finalizes_once_when_repeated():
    transaction = InMemoryPackingTransaction(packages=full_packages())
    finish = FinishPacking(transaction)
    finish.execute(KEY)
    assert finish.execute(KEY).status == OrderStatus.PACKED
    assert transaction.order_saves == 1


def test_packed_event_is_recorded_once_and_a_failed_finish_records_none():
    transaction = InMemoryPackingTransaction(packages=full_packages())
    finish = FinishPacking(transaction)
    finish.execute(KEY)
    finish.execute(KEY)
    assert [e.event_type for e in transaction.events] == ["OrderPacked"]
    assert transaction.events[0].payload["package_ids"] == ["box-0", "box-1"]

    incomplete = InMemoryPackingTransaction(packages=())
    with pytest.raises(OrderError):
        FinishPacking(incomplete).execute(KEY)
    assert incomplete.events == []


@pytest.mark.parametrize("packages", [
    (),
    (package("box-0", content("one", BIN_A, 2), content("one", BIN_B, 1)),),
    (package("box-0", content("one", BIN_A, 1), content("one", BIN_B, 1)),
     package("box-1", content("two", BIN_B, 2))),
])
def test_incomplete_packing_cannot_finish(packages):
    transaction = InMemoryPackingTransaction(packages=packages)
    with pytest.raises(OrderError):
        FinishPacking(transaction).execute(KEY)
    assert transaction.order.status == OrderStatus.PICKED
    assert transaction.order_saves == 0


@pytest.mark.parametrize("status", [
    OrderStatus.ALLOCATED, OrderStatus.PICKING, OrderStatus.SHIPPED, OrderStatus.CANCELLED,
])
def test_only_picked_orders_can_finish_packing(status):
    transaction = InMemoryPackingTransaction(status, full_packages())
    with pytest.raises(OrderError):
        FinishPacking(transaction).execute(KEY)
    assert transaction.order.status == status


def test_finish_packing_of_unknown_order_is_typed_absence():
    with pytest.raises(OrderNotFound):
        FinishPacking(InMemoryPackingTransaction()).execute(OrderKey("owner", "missing"))
