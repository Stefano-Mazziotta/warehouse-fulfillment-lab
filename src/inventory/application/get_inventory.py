"""Read an inventory balance without knowing its storage mechanism."""

from inventory.domain import InventoryBalance, InventoryKey

from .inventory_not_found import InventoryNotFound
from .inventory_repository import InventoryRepository


class GetInventory:
    """Retrieve one balance or report that its stock identity was not found."""

    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def execute(self, key: InventoryKey) -> InventoryBalance:
        balance = self._repository.get(key)
        if balance is None:
            raise InventoryNotFound(f"No inventory balance for {key!r}")
        return balance
