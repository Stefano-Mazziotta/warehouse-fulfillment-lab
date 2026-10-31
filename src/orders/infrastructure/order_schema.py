"""Relational constraints make owner, warehouse and SKU consistency explicit."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)

from inventory.infrastructure.inventory_schema import metadata

orders = Table(
    "orders",
    metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("warehouse_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    UniqueConstraint("client_id", "order_id", "warehouse_id"),
    CheckConstraint(
        "status IN ('CREATED', 'ALLOCATED', 'CANCELLED')",
        name="valid_order_status",
    ),
)

order_lines = Table(
    "order_lines",
    metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("line_id", Text, primary_key=True),
    Column("warehouse_id", Text, nullable=False),
    Column("sku", Text, nullable=False),
    Column("quantity", Integer, nullable=False),
    CheckConstraint("quantity > 0", name="positive_line_quantity"),
    UniqueConstraint("client_id", "order_id", "line_id", "warehouse_id", "sku"),
    ForeignKeyConstraint(
        ["client_id", "order_id", "warehouse_id"],
        ["orders.client_id", "orders.order_id", "orders.warehouse_id"],
    ),
)

reservations = Table(
    "order_reservations",
    metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("line_id", Text, primary_key=True),
    Column("location_id", Text, primary_key=True),
    Column("warehouse_id", Text, nullable=False),
    Column("sku", Text, nullable=False),
    Column("quantity", Integer, nullable=False),
    CheckConstraint("quantity > 0", name="positive_reservation_quantity"),
    ForeignKeyConstraint(
        ["client_id", "order_id", "line_id", "warehouse_id", "sku"],
        [
            "order_lines.client_id",
            "order_lines.order_id",
            "order_lines.line_id",
            "order_lines.warehouse_id",
            "order_lines.sku",
        ],
    ),
    ForeignKeyConstraint(
        ["client_id", "sku", "warehouse_id", "location_id"],
        [
            "inventory_balances.client_id",
            "inventory_balances.sku",
            "inventory_balances.warehouse_id",
            "inventory_balances.location_id",
        ],
    ),
)
