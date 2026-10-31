"""Add the transactional outbox and the consumer inbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_messaging"
down_revision = "0005_shipping"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("outbox_messages",
        sa.Column("message_id", sa.Text(), primary_key=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.CheckConstraint("status IN ('PENDING', 'PUBLISHED', 'DEAD')", name="valid_outbox_status"),
        sa.CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"))
    op.create_index("outbox_due_pending", "outbox_messages", ["next_attempt_at", "created_at"],
                    postgresql_where=sa.text("status = 'PENDING'"))
    op.create_table("inbox_messages",
        sa.Column("consumer_name", sa.Text(), primary_key=True),
        sa.Column("message_id", sa.Text(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")))


def downgrade():
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE outbox_messages, inbox_messages IN ACCESS EXCLUSIVE MODE"))
    # PUBLISHED rows are delivered history. PENDING rows were never sent and DEAD rows were
    # given up on; the inbox is what makes redelivery safe. Dropping any of them loses
    # messaging state that cannot be re-derived from the aggregates.
    if connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM outbox_messages WHERE status IN ('PENDING', 'DEAD')) "
        "OR EXISTS (SELECT 1 FROM inbox_messages)")):
        raise RuntimeError("Downgrade would discard messaging information; drain or reconcile first")
    op.drop_table("inbox_messages")
    op.drop_table("outbox_messages")
