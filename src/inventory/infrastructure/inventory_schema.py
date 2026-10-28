"""SQL mapping mirrors the database constraints installed by Alembic."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    Row,
    Table,
    Text,
    and_,
)
from sqlalchemy.sql.elements import ColumnElement

from inventory.domain import InventoryBalance, InventoryKey

metadata = MetaData()
inventory_balances = Table(
    "inventory_balances",
    metadata,
    *(
        Column(name, Text, primary_key=True)
        for name in ("client_id", "sku", "warehouse_id", "location_id")
    ),
    *(
        Column(name, Integer, nullable=False)
        for name in ("on_hand", "allocated", "picked", "packed")
    ),
    CheckConstraint(
        "on_hand >= 0 AND allocated >= 0 AND picked >= 0 AND packed >= 0",
        name="nonnegative_quantities",
    ),
    CheckConstraint("allocated <= on_hand", name="allocated_within_stock"),
    CheckConstraint("picked <= allocated", name="picked_within_allocated"),
)


def identity(key: InventoryKey) -> ColumnElement[bool]:
    return and_(
        *(
            inventory_balances.c[name] == getattr(key, name)
            for name in ("client_id", "sku", "warehouse_id", "location_id")
        )
    )


def snapshot(row: Row | None) -> InventoryBalance | None:
    if row is None:
        return None
    values = dict(row._mapping)
    key = InventoryKey(
        *(
            values.pop(name)
            for name in ("client_id", "sku", "warehouse_id", "location_id")
        )
    )
    return InventoryBalance(key, **values)
