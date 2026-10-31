from sqlalchemy import Engine, select

from inventory.domain import InventoryBalance, InventoryKey

from .inventory_schema import identity, inventory_balances, snapshot


class PostgresInventoryRepository:

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        statement = select(inventory_balances).where(identity(key))
        with self._engine.connect() as connection:
            return snapshot(connection.execute(statement).first())
