from dataclasses import replace

import pytest

from inventory.infrastructure.in_memory_inventory_repository import (
    InMemoryInventoryRepository,
)
from inventory.domain import InventoryBalance, InventoryKey


def test_reads_seeded_balance():
    key = InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")
    balance = InventoryBalance(key, on_hand=3)

    assert InMemoryInventoryRepository([balance]).get(key) == balance


def test_empty_repository_has_no_balance():
    key = InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")

    assert InMemoryInventoryRepository().get(key) is None


@pytest.mark.parametrize("dimension", ["client_id", "sku", "warehouse_id", "location_id"])
def test_full_stock_identity_is_isolated(dimension):
    key = InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")
    other_key = replace(key, **{dimension: "other"})
    balance = InventoryBalance(key, on_hand=3)
    other_balance = InventoryBalance(other_key, on_hand=8)
    repository = InMemoryInventoryRepository([balance, other_balance])

    assert repository.get(key) == balance
    assert repository.get(other_key) == other_balance
    assert repository.get(replace(key, **{dimension: "missing"})) is None
