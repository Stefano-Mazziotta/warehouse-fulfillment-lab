from typing import Protocol

from orders.application.order_transaction import OrderTransaction
from orders.domain import OrderKey
from packing.domain.package import Package


class PackingTransaction(OrderTransaction, Protocol):
    """Package persistence shares the order's existing transaction and lock."""

    def get_packages(self, key: OrderKey) -> tuple[Package, ...]: ...
    def add_package(self, package: Package) -> None: ...
