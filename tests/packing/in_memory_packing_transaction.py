"""Database-free transaction implementing the order and packing ports.

It keeps the guarantees application code relies on: writes need the order lock,
stock writes need the stock lock, and a failed transaction leaves no trace.
"""
from contextlib import contextmanager
from dataclasses import replace

from inventory.domain import InventoryBalance, InventoryKey
from orders.domain import Order, OrderKey, OrderLine, OrderStatus, Reservation
from packing.domain.package import Package
from packing.domain.package_item import PackageItem

KEY = OrderKey("owner", "order")
WAREHOUSE = "warehouse"
BIN_A = InventoryKey("owner", "sku", WAREHOUSE, "a")
BIN_B = InventoryKey("owner", "sku", WAREHOUSE, "b")

# Line "one" is split across two bins so package contents must name full reservations.
RESERVATIONS = (
    Reservation(KEY, "one", BIN_A, 2, picked_quantity=2),
    Reservation(KEY, "one", BIN_B, 1, picked_quantity=1),
    Reservation(KEY, "two", BIN_B, 2, picked_quantity=2),
)


def content(line_id, stock_key, quantity):
    return PackageItem(KEY, line_id, stock_key, quantity)


def package(package_id, *items, weight_grams=100):
    return Package(KEY, package_id, weight_grams, 200, 150, 100, tuple(items))


def full_packages():
    return (
        package("box-0", content("one", BIN_A, 2), content("one", BIN_B, 1)),
        package("box-1", content("two", BIN_B, 2)),
    )


class InMemoryPackingTransaction:
    _state_names = ("orders", "reservations", "packages", "stock")

    def __init__(self, status=OrderStatus.PICKED, packages=()):
        self.orders = {KEY: Order(
            KEY, WAREHOUSE, (OrderLine("one", "sku", 3), OrderLine("two", "sku", 2)), status)}
        self.reservations = {KEY: RESERVATIONS}
        self.packages = {KEY: tuple(packages)}
        self.stock = {
            BIN_A: InventoryBalance(BIN_A, on_hand=2, allocated=2, picked=2),
            BIN_B: InventoryBalance(BIN_B, on_hand=3, allocated=3, picked=3),
        }
        self.order_saves = 0
        self.stock_saves = 0
        self.active = False
        self._locked_orders: set[OrderKey] = set()
        self._locked_stock: set[InventoryKey] = set()

    @contextmanager
    def __call__(self):
        if self.active:
            raise RuntimeError("Transaction already active")
        snapshot = {name: dict(getattr(self, name)) for name in self._state_names}
        self.active = True
        try:
            yield self
        except BaseException:
            for name, state in snapshot.items():
                setattr(self, name, state)
            raise
        finally:
            self.active = False
            self._locked_orders.clear()
            self._locked_stock.clear()

    @property
    def order(self):
        return self.orders[KEY]

    def set_status(self, status):
        self.orders[KEY] = replace(self.order, status=status)

    def get_order(self, key, *, lock=False):
        order = self.orders.get(key)
        if lock and order is not None:
            self._locked_orders.add(key)
        return order

    def create_order(self, order):
        self.orders.setdefault(order.key, order)
        return self.orders[order.key]

    def save_order(self, order):
        self._require_order_lock(order.key)
        self.orders[order.key] = order
        self.order_saves += 1

    def get_reservations(self, key):
        return self.reservations.get(key, ())

    def add_reservation(self, reservation):
        self._require_order_lock(reservation.order_key)
        self.reservations[reservation.order_key] += (reservation,)

    def save_reservation(self, reservation):
        self._require_order_lock(reservation.order_key)
        self.reservations[reservation.order_key] = tuple(
            reservation if (r.line_id, r.stock_key) == (reservation.line_id, reservation.stock_key)
            else r for r in self.reservations[reservation.order_key])

    def lock_stock(self, order):
        self._require_order_lock(order.key)
        keys = sorted({r.stock_key for r in self.get_reservations(order.key)},
                      key=lambda key: (key.sku, key.location_id))
        self._locked_stock.update(keys)
        return [self.stock[key] for key in keys]

    def save_stock(self, balance):
        if balance.key not in self._locked_stock:
            raise RuntimeError("Stock must be locked before saving")
        self.stock[balance.key] = balance
        self.stock_saves += 1

    def get_packages(self, key):
        return self.packages.get(key, ())

    def add_package(self, package):
        self._require_order_lock(package.order_key)
        self.packages[package.order_key] += (package,)

    def _require_order_lock(self, key):
        if key not in self._locked_orders:
            raise RuntimeError("Order must be locked before writing")
