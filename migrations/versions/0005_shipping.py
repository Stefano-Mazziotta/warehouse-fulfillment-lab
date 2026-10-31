"""Persist one immutable shipping attempt per order and allow the SHIPPED status."""
from alembic import op
import sqlalchemy as sa

revision = "0005_shipping"
down_revision = "0004_packing"
branch_labels = None
depends_on = None

STATUSES = "'CREATED', 'ALLOCATED', 'PICKING', 'PICKED', 'PACKED'"


def upgrade():
    op.drop_constraint("valid_order_status", "orders", type_="check")
    op.create_check_constraint(
        "valid_order_status", "orders", f"status IN ({STATUSES}, 'SHIPPED', 'CANCELLED')")
    op.create_table("shipping_attempts",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("tracking_number", sa.Text()),
        sa.UniqueConstraint("attempt_id"),
        sa.CheckConstraint("status IN ('PENDING', 'UNKNOWN', 'SHIPPED')", name="valid_shipment_status"),
        sa.CheckConstraint(
            "(status = 'SHIPPED') = (tracking_number IS NOT NULL)", name="tracking_only_when_shipped"),
        sa.ForeignKeyConstraint(["client_id", "order_id"], ["orders.client_id", "orders.order_id"]))
    op.create_table("shipping_attempt_packages",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("order_id", sa.Text(), primary_key=True),
        sa.Column("package_id", sa.Text(), primary_key=True),
        sa.ForeignKeyConstraint(["client_id", "order_id"],
            ["shipping_attempts.client_id", "shipping_attempts.order_id"]),
        sa.ForeignKeyConstraint(["client_id", "order_id", "package_id"],
            ["packages.client_id", "packages.order_id", "packages.package_id"]))


def downgrade():
    connection = op.get_bind()
    connection.execute(sa.text(
        "LOCK TABLE orders, shipping_attempts, shipping_attempt_packages IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM shipping_attempts) "
        "OR EXISTS (SELECT 1 FROM orders WHERE status = 'SHIPPED')")):
        raise RuntimeError("Downgrade would discard shipping information; reconcile first")
    op.drop_table("shipping_attempt_packages")
    op.drop_table("shipping_attempts")
    op.drop_constraint("valid_order_status", "orders", type_="check")
    op.create_check_constraint(
        "valid_order_status", "orders", f"status IN ({STATUSES}, 'CANCELLED')")
