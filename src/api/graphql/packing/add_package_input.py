import strawberry

from packing.domain.package import Package
from packing.domain.package_item import PackageItem

from ..graphql_context import GraphQLContext
from ..inventory.stock_location_input import StockLocationInput
from ..invalid_input import invalid_input


@strawberry.input(name="PackageContentInput")
class PackageContentInput:

    line_id: str
    stock: StockLocationInput
    quantity: int


@strawberry.input(name="AddPackageInput")
class AddPackageInput:

    order_id: str
    package_id: str
    weight_grams: int
    length_mm: int
    width_mm: int
    height_mm: int
    contents: list[PackageContentInput]

    def to_package(self, context: GraphQLContext) -> Package:
        key = context.order_key(self.order_id)
        with invalid_input():
            return Package(
                key, self.package_id, self.weight_grams, self.length_mm, self.width_mm,
                self.height_mm,
                tuple(
                    PackageItem(key, item.line_id, item.stock.to_inventory_key(context), item.quantity)
                    for item in self.contents))
