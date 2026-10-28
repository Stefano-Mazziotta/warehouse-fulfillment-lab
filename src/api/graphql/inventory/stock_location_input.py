import strawberry

from inventory.domain import InventoryKey

from ..graphql_context import GraphQLContext


@strawberry.input(name="StockLocationInput", description="Where stock sits; the owner is always the caller.")
class StockLocationInput:

    sku: str
    warehouse_id: str
    location_id: str

    def to_inventory_key(self, context: GraphQLContext) -> InventoryKey:
        return InventoryKey(context.client_id, self.sku, self.warehouse_id, self.location_id)
