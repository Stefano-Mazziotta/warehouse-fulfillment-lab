from typing import Protocol

from inventory.domain import InventoryBalance, InventoryKey


class InventoryRepository(Protocol):

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        ...
