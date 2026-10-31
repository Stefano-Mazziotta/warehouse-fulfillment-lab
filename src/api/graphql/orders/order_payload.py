import strawberry

from .order_type import OrderType


@strawberry.type(name="OrderPayload")
class OrderPayload:

    order: OrderType
