"""One connection and row locks live until commit or rollback on context exit."""

from types import TracebackType

from sqlalchemy import Connection, Engine, select, update

from inventory.domain import InventoryBalance, InventoryKey

from .inventory_schema import identity, inventory_balances, snapshot


class PostgresInventoryTransaction:
    """Create a fresh instance per use case; READ COMMITTED sees the winner's update."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.connection: Connection | None = None
        self._locked: set[InventoryKey] = set()

    def __enter__(self) -> "PostgresInventoryTransaction":
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
        self._locked.clear()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self.connection is not None
        try:
            if kind is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
            self.connection = None
            self._locked.clear()

    def get_for_update(self, key: InventoryKey) -> InventoryBalance | None:
        if self.connection is None:
            raise RuntimeError("Transaction is not active")
        statement = select(inventory_balances).where(identity(key)).with_for_update()
        balance = snapshot(self.connection.execute(statement).first())
        if balance is not None:
            self._locked.add(key)
        return balance

    def save(self, balance: InventoryBalance) -> None:
        if self.connection is None or balance.key not in self._locked:
            raise RuntimeError(
                "Balance must be locked in this transaction before saving"
            )
        statement = (
            update(inventory_balances)
            .where(identity(balance.key))
            .values(
                on_hand=balance.on_hand,
                allocated=balance.allocated,
                picked=balance.picked,
                packed=balance.packed,
            )
        )
        self.connection.execute(statement)
