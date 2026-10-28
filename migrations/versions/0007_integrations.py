"""Add the integration event log, reconciliation checkpoints and channel versions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_integrations"
down_revision = "0006_messaging"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("integration_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('RECEIVED', 'PROCESSED', 'FAILED')",
                           name="valid_integration_event_status"))
    op.create_table("integration_checkpoints",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("cursor", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("channel_order_versions",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("channel_order_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("version >= 1", name="positive_channel_version"),
        sa.ForeignKeyConstraint(["client_id", "channel_order_id"],
                                ["orders.client_id", "orders.order_id"]))


def downgrade():
    connection = op.get_bind()
    connection.execute(sa.text(
        "LOCK TABLE integration_events, integration_checkpoints, channel_order_versions "
        "IN ACCESS EXCLUSIVE MODE"))
    # The channel stays the source of truth, but dropping these rows would forget which
    # events were processed, which versions were seen and where reconciliation stopped.
    if connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM integration_events) "
        "OR EXISTS (SELECT 1 FROM integration_checkpoints) "
        "OR EXISTS (SELECT 1 FROM channel_order_versions)")):
        raise RuntimeError("Downgrade would discard integration information; reconcile first")
    op.drop_table("channel_order_versions")
    op.drop_table("integration_checkpoints")
    op.drop_table("integration_events")
