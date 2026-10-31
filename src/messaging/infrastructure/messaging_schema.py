from sqlalchemy import (
    CheckConstraint, Column, DateTime, Index, Integer, Table, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from inventory.infrastructure.inventory_schema import metadata

outbox_messages = Table(
    "outbox_messages", metadata,
    Column("message_id", Text, primary_key=True),
    Column("client_id", Text, nullable=False),
    Column("aggregate_type", Text, nullable=False),
    Column("aggregate_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("last_error", Text),
    CheckConstraint("status IN ('PENDING', 'PUBLISHED', 'DEAD')", name="valid_outbox_status"),
    CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
    # The relay only ever looks at PENDING rows, so only they are indexed.
    Index("outbox_due_pending", "next_attempt_at", "created_at",
          postgresql_where=text("status = 'PENDING'")),
)

inbox_messages = Table(
    "inbox_messages", metadata,
    Column("consumer_name", Text, primary_key=True),
    Column("message_id", Text, primary_key=True),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)
