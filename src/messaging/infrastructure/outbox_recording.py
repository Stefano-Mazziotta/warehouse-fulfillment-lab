from datetime import datetime

from sqlalchemy import Connection, insert

from messaging.domain.integration_event import IntegrationEvent
from messaging.domain.outbox_message import OutboxMessage

from .messaging_schema import outbox_messages


def record_outbox_event(connection: Connection, event: IntegrationEvent, now: datetime) -> None:
    """Insert on the caller's connection: the row commits or rolls back with the business write."""
    message = OutboxMessage.pending(event, now)
    connection.execute(insert(outbox_messages).values(
        message_id=message.message_id,
        client_id=message.client_id,
        aggregate_type=message.aggregate_type,
        aggregate_id=message.aggregate_id,
        event_type=message.event_type,
        payload=dict(message.payload),
        created_at=message.created_at,
        status=message.status.value,
        attempt_count=message.attempt_count,
        next_attempt_at=message.next_attempt_at,
    ))
