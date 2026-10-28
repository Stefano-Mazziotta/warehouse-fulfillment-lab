"""Create inventory balances with a complete stock identity."""

from alembic import op
import sqlalchemy as sa

revision = "0001_inventory"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "inventory_balances",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("sku", sa.Text(), primary_key=True),
        sa.Column("warehouse_id", sa.Text(), primary_key=True),
        sa.Column("location_id", sa.Text(), primary_key=True),
        sa.Column("on_hand", sa.Integer(), nullable=False),
        sa.Column("allocated", sa.Integer(), nullable=False),
        sa.Column("picked", sa.Integer(), nullable=False),
        sa.Column("packed", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "on_hand >= 0 AND allocated >= 0 AND picked >= 0 AND packed >= 0",
            name="nonnegative_quantities",
        ),
        sa.CheckConstraint("allocated <= on_hand", name="allocated_within_stock"),
        sa.CheckConstraint("picked <= allocated", name="picked_within_allocated"),
    )


def downgrade():
    op.drop_table("inventory_balances")
