from types import TracebackType
from typing import Protocol

from inventory.domain import InventoryBalance, InventoryKey


class InventoryTransaction(Protocol):
    """Lock, check and save in one transaction; commit only on clean exit."""

    def __enter__(self) -> "InventoryTransaction": ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def get_for_update(self, key: InventoryKey) -> InventoryBalance | None: ...

    def save(self, balance: InventoryBalance) -> None: ...
