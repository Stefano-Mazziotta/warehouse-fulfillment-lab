from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Integer, Table, Text

from inventory.infrastructure.inventory_schema import metadata

packages = Table(
    "packages", metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("package_id", Text, primary_key=True),
    Column("weight_grams", Integer, nullable=False),
    Column("length_mm", Integer, nullable=False),
    Column("width_mm", Integer, nullable=False),
    Column("height_mm", Integer, nullable=False),
    CheckConstraint("length(trim(package_id)) > 0", name="nonempty_package_id"),
    CheckConstraint(
        "weight_grams > 0 AND length_mm > 0 AND width_mm > 0 AND height_mm > 0",
        name="positive_package_measurements",
    ),
    ForeignKeyConstraint(
        ["client_id", "order_id"],
        ["orders.client_id", "orders.order_id"],
    ),
)

package_items = Table(
    "package_items", metadata,
    Column("client_id", Text, primary_key=True),
    Column("order_id", Text, primary_key=True),
    Column("package_id", Text, primary_key=True),
    Column("line_id", Text, primary_key=True),
    Column("location_id", Text, primary_key=True),
    Column("warehouse_id", Text, nullable=False),
    Column("sku", Text, nullable=False),
    Column("quantity", Integer, nullable=False),
    CheckConstraint("quantity > 0", name="positive_package_item_quantity"),
    ForeignKeyConstraint(
        ["client_id", "order_id", "package_id"],
        ["packages.client_id", "packages.order_id", "packages.package_id"]),
    ForeignKeyConstraint(
        ["client_id", "order_id", "line_id", "warehouse_id", "sku", "location_id"],
        ["order_reservations.client_id", "order_reservations.order_id", "order_reservations.line_id",
         "order_reservations.warehouse_id", "order_reservations.sku", "order_reservations.location_id"]),
)
