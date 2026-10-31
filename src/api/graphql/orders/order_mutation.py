import strawberry
from strawberry import Info

from ..graphql_context import GraphQLContext
from .create_order_input import CreateOrderInput
from .order_payload import OrderPayload
from .order_type import OrderType


@strawberry.type
class OrderMutation:
    """Each mutation maps its input, calls one use case and wraps the result."""

    @strawberry.mutation(description=(
        "Idempotent: repeating the identical order returns it; a different payload under the "
        "same order ID is a CONFLICT."))
    def create_order(self, info: Info[GraphQLContext, None], input: CreateOrderInput) -> OrderPayload:
        context = info.context
        order = context.services.create_order.execute(input.to_order(context))
        return OrderPayload(order=OrderType.from_domain(order))

    @strawberry.mutation(description=(
        "Reserve stock for every line or nothing. Idempotent: an allocated order stays as it is."))
    def allocate_inventory(self, info: Info[GraphQLContext, None], order_id: str) -> OrderPayload:
        context = info.context
        order = context.services.allocate_order.execute(context.order_key(order_id))
        return OrderPayload(order=OrderType.from_domain(order))

    @strawberry.mutation(description=(
        "Allowed before picking starts; releases only unpicked stock. Idempotent."))
    def cancel_order(self, info: Info[GraphQLContext, None], order_id: str) -> OrderPayload:
        context = info.context
        order = context.services.cancel_order.execute(context.order_key(order_id))
        return OrderPayload(order=OrderType.from_domain(order))
