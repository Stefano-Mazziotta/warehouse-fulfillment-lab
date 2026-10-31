import strawberry
from strawberry import Info

from orders.application.order_summary import OrderSummary
from orders.domain import Order

from ..graphql_context import GraphQLContext
from ..packing.package_type import PackageType
from ..shipping.shipment_attempt_type import ShipmentAttemptType
from .order_line_type import OrderLineType
from .order_status_enum import OrderStatusEnum
from .reservation_type import ReservationType


@strawberry.type(name="Order")
class OrderType:
    """Header fields come with the parent; nested collections are batched per request."""

    order_id: str
    warehouse_id: str
    status: OrderStatusEnum

    @classmethod
    def from_summary(cls, summary: OrderSummary) -> "OrderType":
        return cls(
            order_id=summary.order_id, warehouse_id=summary.warehouse_id,
            status=OrderStatusEnum(summary.status.value))

    @classmethod
    def from_domain(cls, order: Order) -> "OrderType":
        return cls(
            order_id=order.key.order_id, warehouse_id=order.warehouse_id,
            status=OrderStatusEnum(order.status.value))

    @strawberry.field
    async def lines(self, info: Info[GraphQLContext, None]) -> list[OrderLineType]:
        lines = await info.context.loaders.lines.load(self.order_id)
        return [OrderLineType.from_domain(line) for line in lines]

    @strawberry.field
    async def reservations(self, info: Info[GraphQLContext, None]) -> list[ReservationType]:
        held = await info.context.loaders.reservations.load(self.order_id)
        return [ReservationType.from_domain(reservation) for reservation in held]

    @strawberry.field
    async def packages(self, info: Info[GraphQLContext, None]) -> list[PackageType]:
        found = await info.context.loaders.packages.load(self.order_id)
        return [PackageType.from_domain(package) for package in found]

    @strawberry.field
    async def shipment(self, info: Info[GraphQLContext, None]) -> ShipmentAttemptType | None:
        attempt = await info.context.loaders.attempts.load(self.order_id)
        return None if attempt is None else ShipmentAttemptType.from_summary(attempt)
