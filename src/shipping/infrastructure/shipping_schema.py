from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Table, Text, UniqueConstraint

from inventory.infrastructure.inventory_schema import metadata

shipping_attempts = Table(
    "shipping_attempts", metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("attempt_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("tracking_number", Text),
    UniqueConstraint("attempt_id"),
    CheckConstraint("status IN ('PENDING', 'UNKNOWN', 'SHIPPED')", name="valid_shipment_status"),
    CheckConstraint(
        "(status = 'SHIPPED') = (tracking_number IS NOT NULL)", name="tracking_only_when_shipped"),
    ForeignKeyConstraint(["client_id", "order_id"], ["orders.client_id", "orders.order_id"]),
)

shipping_attempt_packages = Table(
    "shipping_attempt_packages", metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("package_id", Text, primary_key=True),
    ForeignKeyConstraint(
        ["client_id", "order_id"],
        ["shipping_attempts.client_id", "shipping_attempts.order_id"]),
    ForeignKeyConstraint(
        ["client_id", "order_id", "package_id"],
        ["packages.client_id", "packages.order_id", "packages.package_id"]),
)
