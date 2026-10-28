import strawberry

from orders.domain import Order, OrderLine

from ..graphql_context import GraphQLContext
from ..invalid_input import invalid_input


@strawberry.input(name="OrderLineInput")
class OrderLineInput:

    line_id: str
    sku: str
    quantity: int


@strawberry.input(name="CreateOrderInput")
class CreateOrderInput:

    order_id: str
    warehouse_id: str
    lines: list[OrderLineInput]

    def to_order(self, context: GraphQLContext) -> Order:
        with invalid_input():
            return Order(
                context.order_key(self.order_id),
                self.warehouse_id,
                tuple(OrderLine(line.line_id, line.sku, line.quantity) for line in self.lines),
            )
