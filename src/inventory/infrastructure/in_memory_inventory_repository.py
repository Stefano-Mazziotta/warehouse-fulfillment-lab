from collections.abc import Iterable

from inventory.domain import InventoryBalance, InventoryKey


class InMemoryInventoryRepository:

    def __init__(self, balances: Iterable[InventoryBalance] = ()) -> None:
        self._balances = {balance.key: balance for balance in balances}

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        return self._balances.get(key)
