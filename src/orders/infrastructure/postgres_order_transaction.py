"""Fresh READ COMMITTED transaction: order lock, then sorted stock locks."""

from types import TracebackType

from sqlalchemy import Connection, Engine, Table, and_, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.sql.elements import ColumnElement

from inventory.domain import InventoryBalance, InventoryKey
from inventory.infrastructure.inventory_schema import (
    identity,
    inventory_balances,
    snapshot,
)
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus, Reservation

from packing.domain.package import Package
from packing.domain.package_item import PackageItem
from packing.infrastructure.packing_schema import packages, package_items

from .order_schema import order_lines, orders, reservations


def order_identity(table: Table, key: OrderKey) -> ColumnElement[bool]:
    return and_(table.c.client_id == key.client_id, table.c.order_id == key.order_id)


class PostgresOrderTransaction:

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.connection: Connection | None = None
        self._locked_orders: set[OrderKey] = set()
        self._locked_stock: set[InventoryKey] = set()

    def __enter__(self) -> "PostgresOrderTransaction":
        if self.connection is not None:
            raise RuntimeError("Transaction already active")
        self.connection = self._engine.connect()
        try:
            self.connection.execution_options(isolation_level="READ COMMITTED")
            self.connection.begin()
        except BaseException:
            self.connection.close()
            self.connection = None
            raise
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._connection()
        try:
            if kind is None:
                connection.commit()
            else:
                connection.rollback()
        finally:
            connection.close()
            self.connection = None
            self._locked_orders.clear()
            self._locked_stock.clear()

    def _connection(self) -> Connection:
        if self.connection is None:
            raise RuntimeError("Transaction is not active")
        return self.connection

    def get_order(self, key: OrderKey, *, lock: bool = False) -> Order | None:
        statement = select(orders).where(order_identity(orders, key))
        if lock:
            statement = statement.with_for_update()
        row = self._connection().execute(statement).mappings().first()
        if row is None:
            return None
        if lock:
            self._locked_orders.add(key)
        line_statement = (
            select(order_lines)
            .where(order_identity(order_lines, key))
            .order_by(order_lines.c.line_id)
        )
        lines = self._connection().execute(line_statement).mappings()
        return Order(
            key,
            row["warehouse_id"],
            tuple(
                OrderLine(line["line_id"], line["sku"], line["quantity"])
                for line in lines
            ),
            OrderStatus(row["status"]),
        )

    def create_order(self, order: Order) -> Order:
        # ON CONFLICT waits for concurrent creators. A fresh READ COMMITTED
        # SELECT observes their complete committed order, never partial lines.
        statement = (
            postgres_insert(orders)
            .values(
                client_id=order.key.client_id,
                order_id=order.key.order_id,
                warehouse_id=order.warehouse_id,
                status=order.status.value,
            )
            .on_conflict_do_nothing(index_elements=["client_id", "order_id"])
            .returning(orders.c.order_id)
        )
        inserted = self._connection().execute(statement).scalar_one_or_none()
        if inserted is not None:
            values = [
                dict(
                    client_id=order.key.client_id,
                    order_id=order.key.order_id,
                    warehouse_id=order.warehouse_id,
                    line_id=line.line_id,
                    sku=line.sku,
                    quantity=line.quantity,
                )
                for line in order.lines
            ]
            self._connection().execute(insert(order_lines), values)
        existing = self.get_order(order.key, lock=True)
        assert existing is not None
        if (existing.warehouse_id, existing.lines) != (order.warehouse_id, order.lines):
            raise OrderError("Order key already exists with a different payload")
        return existing

    def lock_stock(self, order: Order) -> list[InventoryBalance]:
        if order.key not in self._locked_orders:
            raise RuntimeError("Lock order before locking stock")
        statement = (
            select(inventory_balances)
            .where(
                inventory_balances.c.client_id == order.key.client_id,
                inventory_balances.c.warehouse_id == order.warehouse_id,
                inventory_balances.c.sku.in_(
                    sorted({line.sku for line in order.lines})
                ),
            )
            .order_by(inventory_balances.c.sku, inventory_balances.c.location_id)
            .with_for_update()
        )
        balances: list[InventoryBalance] = []
        for row in self._connection().execute(statement):
            balance = snapshot(row)
            assert balance is not None
            balances.append(balance)
        self._locked_stock.update(balance.key for balance in balances)
        return balances

    def save_stock(self, balance: InventoryBalance) -> None:
        if balance.key not in self._locked_stock:
            raise RuntimeError("Stock must be locked before saving")
        statement = (
            update(inventory_balances)
            .where(identity(balance.key))
            .values(
                on_hand=balance.on_hand,
                allocated=balance.allocated,
                picked=balance.picked,
                packed=balance.packed,
            )
        )
        self._connection().execute(statement)

    def get_reservations(self, key: OrderKey) -> tuple[Reservation, ...]:
        statement = (
            select(reservations)
            .where(order_identity(reservations, key))
            .order_by(reservations.c.line_id, reservations.c.location_id)
        )
        rows = self._connection().execute(statement).mappings()
        return tuple(
            Reservation(
                key,
                row["line_id"],
                InventoryKey(
                    row["client_id"],
                    row["sku"],
                    row["warehouse_id"],
                    row["location_id"],
                ),
                row["quantity"],
                row["picked_quantity"],
            )
            for row in rows
        )

    def add_reservation(self, reservation: Reservation) -> None:
        if (
            reservation.order_key not in self._locked_orders
            or reservation.stock_key not in self._locked_stock
        ):
            raise RuntimeError("Order and stock must be locked before reserving")
        key = reservation.stock_key
        statement = insert(reservations).values(
            client_id=key.client_id,
            order_id=reservation.order_key.order_id,
            line_id=reservation.line_id,
            warehouse_id=key.warehouse_id,
            sku=key.sku,
            location_id=key.location_id,
            quantity=reservation.quantity,
            picked_quantity=reservation.picked_quantity,
        )
        self._connection().execute(statement)

    def save_reservation(self, reservation: Reservation) -> None:
        if (
            reservation.order_key not in self._locked_orders
            or reservation.stock_key not in self._locked_stock
        ):
            raise RuntimeError("Order and stock must be locked before picking")
        key = reservation.stock_key
        statement = (
            update(reservations)
            .where(
                order_identity(reservations, reservation.order_key),
                reservations.c.line_id == reservation.line_id,
                reservations.c.client_id == key.client_id,
                reservations.c.sku == key.sku,
                reservations.c.warehouse_id == key.warehouse_id,
                reservations.c.location_id == key.location_id,
            )
            .values(picked_quantity=reservation.picked_quantity)
            .returning(reservations.c.line_id)
        )
        if self._connection().execute(statement).scalar_one_or_none() is None:
            raise OrderError("Reservation is missing")

    def save_order(self, order: Order) -> None:
        if order.key not in self._locked_orders:
            raise RuntimeError("Order must be locked before saving")
        statement = (
            update(orders)
            .where(order_identity(orders, order.key))
            .values(status=order.status.value)
        )
        self._connection().execute(statement)

    def get_packages(self, key: OrderKey) -> tuple[Package, ...]:
        headers = self._connection().execute(
            select(packages).where(order_identity(packages, key))
            .order_by(packages.c.package_id)).mappings()
        contents = self._connection().execute(
            select(package_items).where(order_identity(package_items, key))).mappings()
        by_package: dict[str, list[PackageItem]] = {}
        for row in contents:
            by_package.setdefault(row["package_id"], []).append(PackageItem(
                key, row["line_id"], InventoryKey(row["client_id"], row["sku"],
                row["warehouse_id"], row["location_id"]), row["quantity"]))
        return tuple(Package(key, row["package_id"], row["weight_grams"], row["length_mm"],
                             row["width_mm"], row["height_mm"],
                             tuple(by_package.get(row["package_id"], ()))) for row in headers)

    def add_package(self, package: Package) -> None:
        if package.order_key not in self._locked_orders:
            raise RuntimeError("Order must be locked before adding a package")
        key = package.order_key
        self._connection().execute(insert(packages).values(
            client_id=key.client_id, order_id=key.order_id, package_id=package.package_id,
            weight_grams=package.weight_grams, length_mm=package.length_mm,
            width_mm=package.width_mm, height_mm=package.height_mm))
        self._connection().execute(insert(package_items), [dict(
            client_id=key.client_id, order_id=key.order_id, package_id=package.package_id,
            line_id=item.line_id, warehouse_id=item.stock_key.warehouse_id,
            sku=item.stock_key.sku, location_id=item.stock_key.location_id, quantity=item.quantity
        ) for item in package.contents])
