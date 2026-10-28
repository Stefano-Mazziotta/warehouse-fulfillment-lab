import strawberry

from packing.domain.package_item import PackageItem


@strawberry.type(name="PackageContent")
class PackageContentType:

    line_id: str
    sku: str
    warehouse_id: str
    location_id: str
    quantity: int

    @classmethod
    def from_domain(cls, item: PackageItem) -> "PackageContentType":
        stock = item.stock_key
        return cls(
            line_id=item.line_id, sku=stock.sku, warehouse_id=stock.warehouse_id,
            location_id=stock.location_id, quantity=item.quantity)
