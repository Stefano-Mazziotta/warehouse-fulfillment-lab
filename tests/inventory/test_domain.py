from dataclasses import FrozenInstanceError

import pytest

from inventory.domain import InventoryBalance, InventoryError, InventoryKey


@pytest.fixture
def key():
    return InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")


def test_identity_uses_every_scope_dimension(key):
    assert key == InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")
    other_owner = InventoryKey("client-b", key.sku, key.warehouse_id, key.location_id)
    assert len({key, other_owner}) == 2


def test_empty_balance_has_no_available_stock(key):
    assert InventoryBalance(key).available == 0


def test_available_excludes_allocated_units(key):
    assert InventoryBalance(key, on_hand=10, allocated=4, picked=2).available == 6


@pytest.mark.parametrize("field", ["on_hand", "allocated", "picked", "packed"])
@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_rejects_invalid_counts(key, field, value):
    with pytest.raises(InventoryError):
        InventoryBalance(key, **{field: value})


@pytest.mark.parametrize(
    "counts",
    [
        {"on_hand": 1, "allocated": 2},
        {"on_hand": 2, "allocated": 1, "picked": 2},
    ],
)
def test_rejects_inconsistent_counts(key, counts):
    with pytest.raises(InventoryError):
        InventoryBalance(key, **counts)


def test_identity_and_balance_are_immutable(key):
    balance = InventoryBalance(key)
    with pytest.raises(FrozenInstanceError):
        key.sku = "changed"
    with pytest.raises(FrozenInstanceError):
        balance.on_hand = 1


def test_receive_returns_new_balance_without_changing_reservations(key):
    original = InventoryBalance(key, on_hand=5, allocated=3, picked=2, packed=1)
    received = original.receive(4)
    assert received == InventoryBalance(key, on_hand=9, allocated=3, picked=2, packed=1)
    assert original.on_hand == 5
    assert received.key == original.key


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "1"])
def test_rejects_invalid_receipt_without_mutation(key, quantity):
    original = InventoryBalance(key, on_hand=5)
    with pytest.raises(InventoryError):
        original.receive(quantity)
    assert original.on_hand == 5
