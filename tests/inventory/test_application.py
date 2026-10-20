from dataclasses import dataclass

import pytest

from inventory.application.get_inventory import GetInventory, InventoryNotFound
from inventory.domain import InventoryBalance, InventoryKey


@dataclass
class StubRepository:
    result: InventoryBalance | None
    requested_key: InventoryKey | None = None

    def get(self, key: InventoryKey) -> InventoryBalance | None:
        self.requested_key = key
        return self.result


def test_get_inventory_uses_injected_port():
    key = InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")
    balance = InventoryBalance(key, on_hand=5, allocated=2)
    repository = StubRepository(balance)

    assert GetInventory(repository).execute(key) == balance
    assert repository.requested_key == key


def test_missing_inventory_raises_application_error():
    key = InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")
    repository = StubRepository(None)

    with pytest.raises(InventoryNotFound):
        GetInventory(repository).execute(key)

    assert repository.requested_key == key
