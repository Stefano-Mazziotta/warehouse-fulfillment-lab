"""Read-only in-memory adapter for local examples and tests."""

from collections.abc import Iterable

from inventory.domain import InventoryBalance, InventoryKey


class InMemoryInventoryRepository:
    """Read seeded balances from memory for local examples and tests."""

    def __init__(self, balances: Iterable[InventoryBalance] = ()) -> None:
        self._balances = {balance.key: balance for balance in balances}

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        return self._balances.get(key)
