from types import TracebackType

from sqlalchemy import Connection, Engine


class PostgresTransaction:
    """One READ COMMITTED transaction: commit on success, roll back on any error."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.connection: Connection | None = None

    def __enter__(self):
        if self.connection is not None:
            raise RuntimeError("Transaction already active")
        self.connection = self._engine.connect()
        try:
            self.connection.execution_options(isolation_level="READ COMMITTED")
            self.connection.begin()
        except BaseException:
            self.connection.close()
            self.connection = None
            raise
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._connection()
        try:
            if kind is None:
                connection.commit()
            else:
                connection.rollback()
        finally:
            connection.close()
            self.connection = None

    def _connection(self) -> Connection:
        if self.connection is None:
            raise RuntimeError("Transaction is not active")
        return self.connection
