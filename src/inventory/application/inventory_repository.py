"""Read-only persistence contract owned by the application."""

from typing import Protocol

from inventory.domain import InventoryBalance, InventoryKey


class InventoryRepository(Protocol):
    """Read balances by stock identity without choosing a storage mechanism."""

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        """Return the balance for the full stock identity, if present."""
        ...
