from collections.abc import Iterator

from sqlalchemy import Engine, case, select

from messaging.domain.inbound_message import InboundMessage
from messaging.infrastructure.messaging_schema import outbox_messages
from orders.application.project_order_event import STAGES


class PostgresOutboxOrderEvents:
    """Replays the outbox whatever its delivery status: a committed event is a fact even if
    the relay has not published it yet, or gave up (DEAD)."""

    def __init__(self, engine: Engine, batch_size: int = 500) -> None:
        self._engine = engine
        self._batch_size = batch_size

    def events(self) -> Iterator[InboundMessage]:
        # One transaction stamps a single created_at on all its events, so the lifecycle stage
        # breaks the tie meaningfully; message_id only makes the remainder deterministic.
        stage = case({event: position for event, (position, _) in STAGES.items()},
                     value=outbox_messages.c.event_type, else_=0)
        statement = (
            select(outbox_messages)
            .where(outbox_messages.c.aggregate_type == "order")
            .order_by(outbox_messages.c.created_at, stage, outbox_messages.c.message_id)
        )
        # The database enforces what the port promises: this connection cannot write.
        with self._engine.connect().execution_options(postgresql_readonly=True) as connection:
            for row in connection.execute(
                statement.execution_options(yield_per=self._batch_size)
            ).mappings():
                yield InboundMessage(
                    row["message_id"], row["event_type"], row["client_id"], row["payload"])
