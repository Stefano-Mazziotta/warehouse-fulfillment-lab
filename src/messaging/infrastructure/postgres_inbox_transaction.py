from sqlalchemy.dialects.postgresql import insert

from .messaging_schema import inbox_messages
from .postgres_transaction import PostgresTransaction


class PostgresInboxTransaction(PostgresTransaction):
    """Handlers use `connection` so their effects share this transaction with the inbox row."""

    def record_inbox(self, consumer_name: str, message_id: str) -> bool:
        # A concurrent duplicate waits on the unique index until the first delivery
        # commits (then conflicts: no-op) or rolls back (then this one proceeds).
        statement = (
            insert(inbox_messages)
            .values(consumer_name=consumer_name, message_id=message_id)
            .on_conflict_do_nothing()
            .returning(inbox_messages.c.message_id)
        )
        return self._connection().execute(statement).scalar_one_or_none() is not None
