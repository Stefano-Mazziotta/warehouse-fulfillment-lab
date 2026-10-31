"""Long-running outbox relay for the demo, scoped to one client's rows.

GAP WORKAROUND: the lab has the OutboxRelay use case and the RabbitMQ publisher but no
production entry point that loops them (the projection consumer has one, the relay does not).
This adapter-level script wires the same classes the integration tests wire. Claiming only the
demo client's rows keeps the demo from publishing anyone else's pending events.

    LAB_DATABASE_URL and LAB_AMQP_URL must be set; argv[1] is the client id.
"""
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone

from sqlalchemy import create_engine, select

from messaging.application.outbox_relay import OutboxRelay
from messaging.domain.outbox_message import OutboxMessage
from messaging.domain.outbox_status import OutboxStatus
from messaging.infrastructure.messaging_schema import outbox_messages
from messaging.infrastructure.postgres_outbox_transaction import PostgresOutboxTransaction
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher
from observability.configure_logging import configure_logging

POLL_SECONDS = 0.5
logger = logging.getLogger("messaging.relay")


class ClientScopedOutbox(PostgresOutboxTransaction):
    def __init__(self, engine, client_id: str) -> None:
        super().__init__(engine)
        self._client_id = client_id

    def claim_due(self, now: datetime, limit: int) -> list[OutboxMessage]:
        statement = (
            select(outbox_messages)
            .where(outbox_messages.c.status == OutboxStatus.PENDING.value,
                   outbox_messages.c.client_id == self._client_id,
                   outbox_messages.c.next_attempt_at <= now)
            .order_by(outbox_messages.c.created_at, outbox_messages.c.message_id)
            .limit(limit)
            .with_for_update(skip_locked=True))
        return [
            OutboxMessage(
                row["message_id"], row["client_id"], row["aggregate_type"], row["aggregate_id"],
                row["event_type"], row["payload"], row["created_at"], OutboxStatus(row["status"]),
                row["attempt_count"], row["next_attempt_at"], row["last_error"])
            for row in self._connection().execute(statement).mappings()]


def main(client_id: str) -> int:
    configure_logging(level=os.environ.get("LAB_LOG_LEVEL", "INFO"))
    engine = create_engine(os.environ["LAB_DATABASE_URL"])
    publisher = RabbitMqPublisher(os.environ["LAB_AMQP_URL"])
    relay = OutboxRelay(
        lambda: ClientScopedOutbox(engine, client_id), publisher, lambda: datetime.now(timezone.utc))
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    logger.info("outbox relay started", extra={"client_id": client_id})
    while not stop.is_set():
        result = relay.run_once()
        if result.published or result.retried or result.dead:
            logger.info("relay pass", extra={
                "published": result.published, "retried": result.retried, "dead": result.dead})
        stop.wait(POLL_SECONDS)
    publisher.close()
    logger.info("outbox relay stopped", extra={"client_id": client_id})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
