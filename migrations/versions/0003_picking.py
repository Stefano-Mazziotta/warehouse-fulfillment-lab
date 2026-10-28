"""Retain order-owned cumulative picking progress."""

from alembic import op
import sqlalchemy as sa

revision = "0003_picking"
down_revision = "0002_orders"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("order_reservations", sa.Column(
        "picked_quantity", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint(
        "valid_picked_quantity", "order_reservations",
        "picked_quantity >= 0 AND picked_quantity <= quantity")
    op.drop_constraint("valid_order_status", "orders", type_="check")
    op.create_check_constraint(
        "valid_order_status", "orders",
        "status IN ('CREATED', 'ALLOCATED', 'PICKING', 'PICKED', 'CANCELLED')")


def downgrade():
    connection = op.get_bind()
    # Prevent concurrent writes between the information-loss check and DDL.
    connection.execute(sa.text(
        "LOCK TABLE orders, order_reservations IN ACCESS EXCLUSIVE MODE"))
    has_progress = connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM orders WHERE status IN ('PICKING', 'PICKED')) "
        "OR EXISTS (SELECT 1 FROM order_reservations WHERE picked_quantity > 0)"))
    if has_progress:
        raise RuntimeError("Downgrade would discard picking information; reconcile first")
    op.drop_constraint("valid_order_status", "orders", type_="check")
    op.create_check_constraint(
        "valid_order_status", "orders",
        "status IN ('CREATED', 'ALLOCATED', 'CANCELLED')")
    op.drop_constraint("valid_picked_quantity", "order_reservations", type_="check")
    op.drop_column("order_reservations", "picked_quantity")
