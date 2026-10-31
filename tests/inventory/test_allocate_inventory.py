import pytest

from inventory.application.allocate_inventory import AllocateInventory
from inventory.application.inventory_not_found import InventoryNotFound
from inventory.domain import InventoryBalance, InventoryError, InventoryKey

KEY = InventoryKey("owner", "sku", "warehouse", "bin")


class StubTransaction:
    def __init__(self, balance):
        self.balance = balance
        self.events = []

    def __enter__(self):
        self.events.append("begin")
        return self

    def get_for_update(self, key):
        assert key == KEY
        self.events.append("lock")
        return self.balance

    def save(self, balance):
        self.events.append("save")
        self.balance = balance

    def __exit__(self, kind, value, traceback):
        self.events.append("rollback" if kind else "commit")


def test_allocation_is_one_transaction():
    transaction = StubTransaction(InventoryBalance(KEY, on_hand=2))
    result = AllocateInventory(lambda: transaction).execute(KEY, 1)
    assert result.allocated == 1
    assert transaction.events == ["begin", "lock", "save", "commit"]


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, 3])
def test_invalid_allocation_rolls_back_without_save(quantity):
    transaction = StubTransaction(InventoryBalance(KEY, on_hand=2))
    with pytest.raises(InventoryError):
        AllocateInventory(lambda: transaction).execute(KEY, quantity)
    assert transaction.events == ["begin", "lock", "rollback"]
    assert transaction.balance.allocated == 0


def test_missing_balance_rolls_back():
    transaction = StubTransaction(None)
    with pytest.raises(InventoryNotFound):
        AllocateInventory(lambda: transaction).execute(KEY, 1)
    assert transaction.events == ["begin", "lock", "rollback"]


def test_postgres_transaction_closes_connection_when_begin_fails():
    from unittest.mock import Mock

    from inventory.infrastructure.postgres_inventory_transaction import (
        PostgresInventoryTransaction,
    )

    connection = Mock()
    connection.begin.side_effect = RuntimeError("begin failed")
    engine = Mock()
    engine.connect.return_value = connection
    connection.execution_options.return_value = connection
    transaction = PostgresInventoryTransaction(engine)

    with pytest.raises(RuntimeError, match="begin failed"):
        transaction.__enter__()

    connection.close.assert_called_once_with()
    assert transaction.connection is None
