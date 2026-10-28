"""Shared fixtures for the messaging proofs; every test runs in a disposable schema."""
from pathlib import Path
import sys

for sibling in ("packing", "shipping"):
    sys.path.append(str(Path(__file__).resolve().parents[1] / sibling))

from sqlalchemy import select  # noqa: E402

from messaging.domain.outbox_status import OutboxStatus  # noqa: E402
from messaging.infrastructure.messaging_schema import outbox_messages  # noqa: E402


def outbox_rows(engine, *statuses):
    statement = select(outbox_messages).order_by(outbox_messages.c.created_at, outbox_messages.c.message_id)
    if statuses:
        statement = statement.where(outbox_messages.c.status.in_([s.value for s in statuses]))
    with engine.connect() as connection:
        return list(connection.execute(statement).mappings())


def event_types(engine):
    return [row["event_type"] for row in outbox_rows(engine)]


def pending_rows(engine):
    return outbox_rows(engine, OutboxStatus.PENDING)
