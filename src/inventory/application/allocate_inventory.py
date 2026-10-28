from collections.abc import Callable

from inventory.domain import InventoryBalance, InventoryKey

from .inventory_not_found import InventoryNotFound
from .inventory_transaction import InventoryTransaction


class AllocateInventory:

    def __init__(self, transaction_factory: Callable[[], InventoryTransaction]) -> None:
        self._transaction_factory = transaction_factory

    def execute(self, key: InventoryKey, quantity: int) -> InventoryBalance:
        with self._transaction_factory() as transaction:
            balance = transaction.get_for_update(key)
            if balance is None:
                raise InventoryNotFound(f"No inventory balance for {key!r}")
            allocated = balance.allocate(quantity)
            transaction.save(allocated)
        return allocated
