from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from integrations.domain.channel_cursor import ChannelCursor
from messaging.infrastructure.postgres_transaction import PostgresTransaction

from .integrations_schema import integration_checkpoints as checkpoints


class PostgresReconciliationTransaction(PostgresTransaction):

    def lock_cursor(self, source: str, client_id: str) -> ChannelCursor | None:
        connection = self._connection()
        connection.execute(
            insert(checkpoints)
            .values(source=source, client_id=client_id, updated_at=func.now())
            .on_conflict_do_nothing()
        )
        # A competing reconciler for the same owner waits here until we commit,
        # then reads the checkpoint we advanced instead of the one we started from.
        token = connection.execute(
            select(checkpoints.c.cursor)
            .where(checkpoints.c.source == source, checkpoints.c.client_id == client_id)
            .with_for_update()
        ).scalar_one()
        return None if token is None else ChannelCursor.from_token(token)

    def advance(self, source: str, client_id: str, cursor: ChannelCursor, at: datetime) -> None:
        self._connection().execute(
            update(checkpoints)
            .where(checkpoints.c.source == source, checkpoints.c.client_id == client_id)
            .values(cursor=cursor.to_token(), updated_at=at)
        )
