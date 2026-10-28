import strawberry
from strawberry import Info

from inventory.domain import InventoryKey

from ..graphql_context import GraphQLContext
from .inventory_balance_type import InventoryBalanceType


@strawberry.type
class InventoryQuery:

    @strawberry.field(description="Stock of the calling client at one location; NOT_FOUND otherwise.")
    def inventory_balance(
        self, info: Info[GraphQLContext, None], sku: str, warehouse_id: str, location_id: str
    ) -> InventoryBalanceType | None:
        context = info.context
        key = InventoryKey(context.client_id, sku, warehouse_id, location_id)
        return InventoryBalanceType.from_domain(context.services.get_inventory.execute(key))
