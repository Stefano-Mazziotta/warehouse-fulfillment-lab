from collections.abc import Sequence

from sqlalchemy import Engine, select

from inventory.domain import InventoryKey
from orders.application.order_summary import OrderSummary
from orders.domain import OrderKey, OrderLine, OrderStatus, Reservation

from .order_schema import order_lines, orders, reservations


class PostgresOrderQueries:
    """Read-only; each call is one statement on a short-lived connection, no row locks."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_summary(self, client_id: str, order_id: str) -> OrderSummary | None:
        statement = select(orders).where(
            orders.c.client_id == client_id, orders.c.order_id == order_id
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else self._summary(row)

    def list_summaries(
        self, client_id: str, after_order_id: str | None, limit: int
    ) -> tuple[OrderSummary, ...]:
        statement = select(orders).where(orders.c.client_id == client_id)
        if after_order_id is not None:
            statement = statement.where(orders.c.order_id > after_order_id)
        statement = statement.order_by(orders.c.order_id).limit(limit)
        with self._engine.connect() as connection:
            return tuple(self._summary(row) for row in connection.execute(statement).mappings())

    def lines_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[OrderLine, ...]]:
        statement = (
            select(order_lines)
            .where(order_lines.c.client_id == client_id, order_lines.c.order_id.in_(order_ids))
            .order_by(order_lines.c.order_id, order_lines.c.line_id)
        )
        grouped: dict[str, list[OrderLine]] = {}
        with self._engine.connect() as connection:
            for row in connection.execute(statement).mappings():
                grouped.setdefault(row["order_id"], []).append(
                    OrderLine(row["line_id"], row["sku"], row["quantity"])
                )
        return {order_id: tuple(lines) for order_id, lines in grouped.items()}

    def reservations_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[Reservation, ...]]:
        statement = (
            select(reservations)
            .where(reservations.c.client_id == client_id, reservations.c.order_id.in_(order_ids))
            .order_by(reservations.c.order_id, reservations.c.line_id, reservations.c.location_id)
        )
        grouped: dict[str, list[Reservation]] = {}
        with self._engine.connect() as connection:
            for row in connection.execute(statement).mappings():
                grouped.setdefault(row["order_id"], []).append(Reservation(
                    OrderKey(client_id, row["order_id"]),
                    row["line_id"],
                    InventoryKey(client_id, row["sku"], row["warehouse_id"], row["location_id"]),
                    row["quantity"],
                    row["picked_quantity"],
                ))
        return {order_id: tuple(items) for order_id, items in grouped.items()}

    @staticmethod
    def _summary(row) -> OrderSummary:
        return OrderSummary(row["order_id"], row["warehouse_id"], OrderStatus(row["status"]))
