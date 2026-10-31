import strawberry
from strawberry import Info

from orders.domain import Reservation

from ..graphql_context import GraphQLContext
from ..invalid_input import invalid_input
from ..orders.order_payload import OrderPayload
from ..orders.order_type import OrderType
from ..orders.reservation_type import ReservationType
from .record_pick_input import RecordPickInput
from .record_pick_payload import RecordPickPayload


@strawberry.type
class PickingMutation:

    @strawberry.mutation(description=(
        "ALLOCATED to PICKING. Idempotent; cancellation is no longer possible afterwards."))
    def start_picking(self, info: Info[GraphQLContext, None], order_id: str) -> OrderPayload:
        context = info.context
        order = context.services.start_picking.execute(context.order_key(order_id))
        return OrderPayload(order=OrderType.from_domain(order))

    @strawberry.mutation(description=(
        "Sets the cumulative picked quantity of one reservation. Idempotent: the same target is a "
        "no-op and a lower one is a CONFLICT."))
    def record_pick(self, info: Info[GraphQLContext, None], input: RecordPickInput) -> RecordPickPayload:
        context = info.context
        key = context.order_key(input.order_id)
        with invalid_input():
            stock = input.stock.to_inventory_key(context)
        reservation: Reservation = context.services.record_pick.execute(
            key, input.line_id, stock, input.picked_quantity)
        return RecordPickPayload(reservation=ReservationType.from_domain(reservation))

    @strawberry.mutation(description=(
        "PICKING to PICKED once every reservation is fully picked. Idempotent."))
    def complete_picking(self, info: Info[GraphQLContext, None], order_id: str) -> OrderPayload:
        context = info.context
        order = context.services.complete_picking.execute(context.order_key(order_id))
        return OrderPayload(order=OrderType.from_domain(order))
