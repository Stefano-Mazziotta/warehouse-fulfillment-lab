"""Loaders batch within one top-level mutation field but must not serve stale data to the next one.

Database-free: the use cases are fakes over a small mutable warehouse, so the only thing under
test is when the per-request loaders are discarded.
"""
import asyncio
from types import SimpleNamespace

from api_support import attach
from sqlalchemy import create_engine

from api.app_config import AppConfig
from api.graphql.request_loaders import RequestLoaders
from inventory.domain import InventoryKey
from orders.domain import OrderKey, OrderStatus, Reservation
from packing.domain.package import Package
from packing.domain.package_item import PackageItem

KEY = OrderKey("owner", "o1")
STOCK = InventoryKey("owner", "sku", "w1", "a")
STOCK_INPUT = {"sku": "sku", "warehouseId": "w1", "locationId": "a"}


class FakeWarehouse:
    """One order with one reservation of 2; reads count how often a loader really queried."""

    def __init__(self) -> None:
        self.picked = 0
        self.packages: list[Package] = []
        self.reads = 0
        self.services = SimpleNamespace(
            start_picking=SimpleNamespace(execute=lambda key: self._order()),
            complete_picking=SimpleNamespace(execute=lambda key: self._order()),
            finish_packing=SimpleNamespace(execute=lambda key: self._order()),
            record_pick=SimpleNamespace(execute=self._record_pick),
            add_package=SimpleNamespace(execute=self._add_package),
            order_queries=SimpleNamespace(reservations_for=self._reservations_for),
            package_queries=SimpleNamespace(packages_for=self._packages_for),
            receive_channel_event=None,
        )

    def _order(self):
        return SimpleNamespace(key=KEY, warehouse_id="w1", status=OrderStatus.PICKING)

    def _record_pick(self, key, line_id, stock, target):
        self.picked = target
        return self._reservation()

    def _add_package(self, package):
        self.packages.append(package)
        return package

    def _reservation(self) -> Reservation:
        return Reservation(KEY, "l1", STOCK, 2, self.picked)

    def _reservations_for(self, client_id, order_ids):
        self.reads += 1
        return {order_id: (self._reservation(),) for order_id in order_ids}

    def _packages_for(self, client_id, order_ids):
        self.reads += 1
        return {order_id: tuple(self.packages) for order_id in order_ids}


def api_over(warehouse: FakeWarehouse):
    return attach(create_engine("sqlite://"), AppConfig(database_url="sqlite://"), warehouse.services)


def test_a_later_mutation_field_sees_the_write_of_an_earlier_one():
    lab = api_over(FakeWarehouse())
    data = lab.ok("""mutation($pick: RecordPickInput!) {
        before: startPicking(orderId: "o1") { order { reservations { pickedQuantity } } }
        pick: recordPick(input: $pick) { reservation { pickedQuantity } }
        after: completePicking(orderId: "o1") { order { reservations { pickedQuantity } } }
    }""", {"pick": {"orderId": "o1", "lineId": "l1", "stock": STOCK_INPUT, "pickedQuantity": 1}})
    assert data["before"]["order"]["reservations"] == [{"pickedQuantity": 0}]
    assert data["pick"]["reservation"]["pickedQuantity"] == 1
    assert data["after"]["order"]["reservations"] == [{"pickedQuantity": 1}]


def test_a_package_added_by_an_earlier_field_is_visible_to_a_later_one():
    lab = api_over(FakeWarehouse())
    data = lab.ok("""mutation($package: AddPackageInput!) {
        before: startPicking(orderId: "o1") { order { packages { packageId } } }
        add: addPackage(input: $package) { package { packageId } }
        after: finishPacking(orderId: "o1") { order { packages { packageId } } }
    }""", {"package": {
        "orderId": "o1", "packageId": "p1", "weightGrams": 500, "lengthMm": 100, "widthMm": 100,
        "heightMm": 100, "contents": [{"lineId": "l1", "stock": STOCK_INPUT, "quantity": 2}]}})
    assert data["before"]["order"]["packages"] == []
    assert data["after"]["order"]["packages"] == [{"packageId": "p1"}]


def test_reads_inside_one_field_are_still_batched():
    warehouse = FakeWarehouse()
    lab = api_over(warehouse)
    lab.ok("""mutation { startPicking(orderId: "o1") { order {
        a: reservations { pickedQuantity } b: reservations { quantity } } } }""")
    assert warehouse.reads == 1


def test_reset_discards_cached_values_and_keeps_batching_afterwards():
    warehouse = FakeWarehouse()
    loaders = RequestLoaders(warehouse.services, "owner")

    async def load_twice() -> None:
        await asyncio.gather(loaders.reservations.load("o1"), loaders.reservations.load("o1"))
        await loaders.reservations.load("o1")

    asyncio.run(load_twice())
    assert warehouse.reads == 1  # one batch, then served from the cache
    loaders.reset()
    asyncio.run(load_twice())
    assert warehouse.reads == 2
