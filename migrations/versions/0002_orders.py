"""Create orders and their line-attributed stock reservations."""

from alembic import op
import sqlalchemy as sa

revision = "0002_orders"
down_revision = "0001_inventory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orders",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("warehouse_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.UniqueConstraint("client_id", "order_id", "warehouse_id"),
        sa.CheckConstraint(
            "status IN ('CREATED', 'ALLOCATED', 'CANCELLED')",
            name="valid_order_status",
        ),
    )
    op.create_table(
        "order_lines",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("line_id", sa.Text(), primary_key=True),
        sa.Column("warehouse_id", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="positive_line_quantity"),
        sa.UniqueConstraint("client_id", "order_id", "line_id", "warehouse_id", "sku"),
        sa.ForeignKeyConstraint(
            ["client_id", "order_id", "warehouse_id"],
            ["orders.client_id", "orders.order_id", "orders.warehouse_id"],
        ),
    )
    op.create_table(
        "order_reservations",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("line_id", sa.Text(), primary_key=True),
        sa.Column("location_id", sa.Text(), primary_key=True),
        sa.Column("warehouse_id", sa.Text(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="positive_reservation_quantity"),
        sa.ForeignKeyConstraint(
            ["client_id", "order_id", "line_id", "warehouse_id", "sku"],
            [
                "order_lines.client_id",
                "order_lines.order_id",
                "order_lines.line_id",
                "order_lines.warehouse_id",
                "order_lines.sku",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "sku", "warehouse_id", "location_id"],
            [
                "inventory_balances.client_id",
                "inventory_balances.sku",
                "inventory_balances.warehouse_id",
                "inventory_balances.location_id",
            ],
        ),
    )


def downgrade():
    op.drop_table("order_reservations")
    op.drop_table("order_lines")
    op.drop_table("orders")
