from functools import partial

import strawberry

from ..app_config import AppConfig
from .error_mapping import ErrorMapping
from .fresh_loaders_per_mutation_field import FreshLoadersPerMutationField
from .inventory.inventory_query import InventoryQuery
from .orders.order_mutation import OrderMutation
from .orders.order_query import OrderQuery
from .packing.packing_mutation import PackingMutation
from .picking.picking_mutation import PickingMutation
from .query_limits import QueryLimits
from .shipping.shipping_mutation import ShippingMutation


@strawberry.type
class Query(OrderQuery, InventoryQuery):
    pass


@strawberry.type
class Mutation(OrderMutation, PickingMutation, PackingMutation, ShippingMutation):
    pass


def build_schema(config: AppConfig) -> strawberry.Schema:
    return strawberry.Schema(
        query=Query,
        mutation=Mutation,
        # A factory (not an instance) gives every request its own extension object.
        extensions=[ErrorMapping, FreshLoadersPerMutationField, partial(QueryLimits, config)],
    )
