"""Persist immutable packages and their complete owned reservation identity."""
from alembic import op
import sqlalchemy as sa

revision = "0004_packing"
down_revision = "0003_picking"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("valid_order_status", "orders", type_="check")
    op.create_check_constraint(
        "valid_order_status",
        "orders",
        "status IN ('CREATED', 'ALLOCATED', 'PICKING', 'PICKED', 'PACKED', 'CANCELLED')",
    )
    op.create_unique_constraint("reservation_full_identity", "order_reservations",
        ["client_id", "order_id", "line_id", "warehouse_id", "sku", "location_id"])
    op.create_table("packages",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("package_id", sa.Text(), primary_key=True),
        sa.Column("weight_grams", sa.Integer(), nullable=False),
        sa.Column("length_mm", sa.Integer(), nullable=False),
        sa.Column("width_mm", sa.Integer(), nullable=False),
        sa.Column("height_mm", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(trim(package_id)) > 0", name="nonempty_package_id"),
        sa.CheckConstraint(
            "weight_grams > 0 AND length_mm > 0 AND width_mm > 0 AND height_mm > 0",
            name="positive_package_measurements",
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "order_id"],
            ["orders.client_id", "orders.order_id"],
        ))
    op.create_table("package_items",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("package_id", sa.Text(), primary_key=True),
        sa.Column("line_id", sa.Text(), primary_key=True),
        sa.Column("location_id", sa.Text(), primary_key=True),
        sa.Column("warehouse_id", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="positive_package_item_quantity"),
        sa.ForeignKeyConstraint(["client_id", "order_id", "package_id"],
            ["packages.client_id", "packages.order_id", "packages.package_id"]),
        sa.ForeignKeyConstraint(["client_id", "order_id", "line_id", "warehouse_id", "sku", "location_id"],
            ["order_reservations.client_id", "order_reservations.order_id", "order_reservations.line_id",
             "order_reservations.warehouse_id", "order_reservations.sku", "order_reservations.location_id"]))


def downgrade():
    connection = op.get_bind()
    # The check and the destructive DDL must share locks, not a race window.
    connection.execute(sa.text(
        "LOCK TABLE orders, order_reservations, packages, package_items IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM packages) "
        "OR EXISTS (SELECT 1 FROM orders WHERE status = 'PACKED')")):
        raise RuntimeError("Downgrade would discard packing information; reconcile first")
    op.drop_table("package_items")
    op.drop_table("packages")
    op.drop_constraint(
        "reservation_full_identity",
        "order_reservations",
        type_="unique",
    )
    op.drop_constraint("valid_order_status", "orders", type_="check")
    op.create_check_constraint("valid_order_status", "orders",
        "status IN ('CREATED', 'ALLOCATED', 'PICKING', 'PICKED', 'CANCELLED')")
