from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError, OrderStatus
from packing.domain.package import Package
from packing.domain.packing_config import PackingConfig

from .packing_transaction import PackingTransaction


class AddPackage:
    """Append one immutable package, serialized by the owning order lock."""

    def __init__(self, transaction: Callable[[], AbstractContextManager[PackingTransaction]]) -> None:
        self._transaction = transaction

    def execute(self, package: Package) -> Package:
        with self._transaction() as transaction:
            order = transaction.get_order(package.order_key, lock=True)
            if order is None:
                raise OrderNotFound(package.order_key)
            packages = transaction.get_packages(order.key)
            existing = next(
                (item for item in packages if item.package_id == package.package_id),
                None,
            )
            if existing is not None:
                if existing != package:
                    raise OrderError("Package ID already exists with a different payload")
                return existing
            if order.status != OrderStatus.PICKED:
                raise OrderError("Only PICKED orders accept new packages")
            PackingConfig(order, transaction.get_reservations(order.key),
                          (*packages, package)).validate()
            transaction.add_package(package)
            return package
