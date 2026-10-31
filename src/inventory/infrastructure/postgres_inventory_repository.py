"""Read-only PostgreSQL adapter; queries never imply write authorization."""

from sqlalchemy import Engine, select

from inventory.domain import InventoryBalance, InventoryKey

from .inventory_schema import identity, inventory_balances, snapshot


class PostgresInventoryRepository:
    """Retrieve immutable balance snapshots without exposing write operations."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        statement = select(inventory_balances).where(identity(key))
        with self._engine.connect() as connection:
            return snapshot(connection.execute(statement).first())
