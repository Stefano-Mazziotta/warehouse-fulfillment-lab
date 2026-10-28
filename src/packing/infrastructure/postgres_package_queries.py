from collections.abc import Sequence

from sqlalchemy import Engine, select

from inventory.domain import InventoryKey
from orders.domain import OrderKey
from packing.domain.package import Package
from packing.domain.package_item import PackageItem

from .packing_schema import package_items, packages


class PostgresPackageQueries:

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def packages_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[Package, ...]]:
        headers = (
            select(packages)
            .where(packages.c.client_id == client_id, packages.c.order_id.in_(order_ids))
            .order_by(packages.c.order_id, packages.c.package_id)
        )
        contents = select(package_items).where(
            package_items.c.client_id == client_id, package_items.c.order_id.in_(order_ids)
        )
        with self._engine.connect() as connection:
            header_rows = connection.execute(headers).mappings().all()
            content_rows = connection.execute(contents).mappings().all()
        items: dict[tuple[str, str], list[PackageItem]] = {}
        for row in content_rows:
            order_key = OrderKey(client_id, row["order_id"])
            items.setdefault((row["order_id"], row["package_id"]), []).append(PackageItem(
                order_key, row["line_id"],
                InventoryKey(client_id, row["sku"], row["warehouse_id"], row["location_id"]),
                row["quantity"],
            ))
        grouped: dict[str, list[Package]] = {}
        for row in header_rows:
            grouped.setdefault(row["order_id"], []).append(Package(
                OrderKey(client_id, row["order_id"]), row["package_id"], row["weight_grams"],
                row["length_mm"], row["width_mm"], row["height_mm"],
                tuple(items[(row["order_id"], row["package_id"])]),
            ))
        return {order_id: tuple(found) for order_id, found in grouped.items()}
