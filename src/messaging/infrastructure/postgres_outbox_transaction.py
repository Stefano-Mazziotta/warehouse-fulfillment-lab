from datetime import datetime

from sqlalchemy import select, update

from messaging.domain.outbox_message import OutboxMessage
from messaging.domain.outbox_status import OutboxStatus

from .messaging_schema import outbox_messages
from .postgres_transaction import PostgresTransaction


class PostgresOutboxTransaction(PostgresTransaction):

    def claim_due(self, now: datetime, limit: int) -> list[OutboxMessage]:
        # SKIP LOCKED: a row another relay is publishing is invisible to this one, so
        # relays never wait on each other and never double-claim. Order is best-effort.
        statement = (
            select(outbox_messages)
            .where(outbox_messages.c.status == OutboxStatus.PENDING.value,
                   outbox_messages.c.next_attempt_at <= now)
            .order_by(outbox_messages.c.created_at, outbox_messages.c.message_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [
            OutboxMessage(
                row["message_id"], row["client_id"], row["aggregate_type"], row["aggregate_id"],
                row["event_type"], row["payload"], row["created_at"], OutboxStatus(row["status"]),
                row["attempt_count"], row["next_attempt_at"], row["last_error"])
            for row in self._connection().execute(statement).mappings()
        ]

    def save(self, message: OutboxMessage) -> None:
        # Only delivery bookkeeping changes; the event itself is immutable.
        self._connection().execute(
            update(outbox_messages)
            .where(outbox_messages.c.message_id == message.message_id)
            .values(status=message.status.value, attempt_count=message.attempt_count,
                    next_attempt_at=message.next_attempt_at, last_error=message.last_error))
