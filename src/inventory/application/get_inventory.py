"""Read an inventory balance without knowing its storage mechanism."""

from inventory.domain import InventoryBalance, InventoryKey

from .ports import InventoryRepository


class InventoryNotFound(LookupError):
    """No balance exists for the requested stock identity."""


class GetInventory:
    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def execute(self, key: InventoryKey) -> InventoryBalance:
        balance = self._repository.get(key)
        if balance is None:
            raise InventoryNotFound(f"No inventory balance for {key!r}")
        return balance
