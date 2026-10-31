import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from sqlalchemy import Engine, select, tuple_
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from integrations.domain.channel_cursor import ChannelCursor
from integrations.domain.channel_event import ChannelEvent
from integrations.domain.channel_order import ChannelOrder
from integrations.domain.channel_order_line import ChannelOrderLine
from integrations.domain.channel_order_page import ChannelOrderPage

from .channel_webhooks import ChannelWebhooks
from .fake_channel_schema import channel_metadata, fake_channel_orders as table


class PostgresFakeSalesChannel:
    """Durable fake channel: every call is its own committed transaction."""

    def __init__(
        self,
        engine: Engine,
        webhooks: ChannelWebhooks,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._engine = engine
        self.webhooks = webhooks
        self._clock = clock

    @staticmethod
    def install(engine: Engine) -> None:
        channel_metadata.create_all(engine)

    def upsert(
        self,
        client_id: str,
        channel_order_id: str,
        warehouse_id: str,
        lines: Sequence[ChannelOrderLine],
        *,
        updated_at: datetime | None = None,
    ) -> ChannelEvent:
        encoded = json.dumps([[l.line_id, l.sku, l.quantity] for l in lines])
        moment = updated_at or self._clock()
        insert = postgres_insert(table).values(
            client_id=client_id, channel_order_id=channel_order_id,
            warehouse_id=warehouse_id, lines=encoded, version=1, updated_at=moment,
        )
        statement = insert.on_conflict_do_update(
            index_elements=["client_id", "channel_order_id"],
            set_=dict(warehouse_id=warehouse_id, lines=encoded,
                      version=table.c.version + 1, updated_at=moment),
        ).returning(table)
        with self._engine.begin() as connection:
            row = connection.execute(statement).one()
        return self.webhooks.publish(self._order(row))

    def list_orders_updated_since(
        self, client_id: str, cursor: ChannelCursor | None, limit: int
    ) -> ChannelOrderPage:
        statement = select(table).where(table.c.client_id == client_id)
        if cursor is not None:
            statement = statement.where(
                tuple_(table.c.updated_at, table.c.channel_order_id)
                > tuple_(cursor.updated_at, cursor.order_id)
            )
        statement = statement.order_by(table.c.updated_at, table.c.channel_order_id).limit(limit + 1)
        with self._engine.connect() as connection:
            rows = connection.execute(statement).all()
        return ChannelOrderPage(tuple(self._order(r) for r in rows[:limit]), len(rows) > limit)

    @staticmethod
    def _order(row) -> ChannelOrder:
        return ChannelOrder(
            row.client_id, row.channel_order_id, row.warehouse_id,
            tuple(ChannelOrderLine(*line) for line in json.loads(row.lines)),
            row.version, row.updated_at,
        )
