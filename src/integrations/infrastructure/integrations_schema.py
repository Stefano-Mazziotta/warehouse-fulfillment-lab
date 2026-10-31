from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKeyConstraint, Integer, Table, Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from inventory.infrastructure.inventory_schema import metadata
# Registers orders so the foreign key below resolves.
from orders.infrastructure import order_schema  # noqa: F401

integration_events = Table(
    "integration_events", metadata,
    Column("id", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("client_id", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("detail", Text),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('RECEIVED', 'PROCESSED', 'FAILED')", name="valid_integration_event_status"),
)

integration_checkpoints = Table(
    "integration_checkpoints", metadata,
    Column("source", Text, primary_key=True),
    Column("client_id", Text, primary_key=True),
    Column("cursor", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

channel_order_versions = Table(
    "channel_order_versions", metadata,
    Column("source", Text, primary_key=True),
    Column("client_id", Text, primary_key=True),
    Column("channel_order_id", Text, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("content", JSONB, nullable=False),
    CheckConstraint("version >= 1", name="positive_channel_version"),
    ForeignKeyConstraint(
        ["client_id", "channel_order_id"], ["orders.client_id", "orders.order_id"]
    ),
)
