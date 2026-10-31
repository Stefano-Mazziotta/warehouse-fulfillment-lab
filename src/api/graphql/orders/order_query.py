import strawberry
from strawberry import Info

from orders.domain import OrderStatus

from ..bad_user_input import BadUserInput
from ..graphql_context import GraphQLContext
from ..page_info_type import PageInfoType
from .order_connection_type import OrderConnectionType
from .order_cursor import decode_order_cursor, encode_order_cursor
from .order_type import OrderType


@strawberry.type
class OrderQuery:

    @strawberry.field(description="One order of the calling client; NOT_FOUND for anyone else's.")
    def order(self, info: Info[GraphQLContext, None], order_id: str) -> OrderType | None:
        context = info.context
        summary = context.services.get_order_summary.execute(context.order_key(order_id))
        return OrderType.from_summary(summary)

    @strawberry.field(description=(
        "Keyset-paginated orders of the calling client, ascending by order ID. "
        "`first` defaults to the configured page size and is capped at the configured maximum."))
    def orders(
        self, info: Info[GraphQLContext, None], first: int | None = None, after: str | None = None
    ) -> OrderConnectionType:
        context = info.context
        limit = context.config.default_page_size if first is None else first
        if not 1 <= limit <= context.config.max_page_size:
            raise BadUserInput(f"first must be between 1 and {context.config.max_page_size}")
        cursor = None if after is None else decode_order_cursor(after)
        page = context.services.list_orders.execute(context.client_id, cursor, limit)
        nodes = [OrderType.from_summary(summary) for summary in page.items]
        end_cursor = encode_order_cursor(page.items[-1].order_id) if page.items else None
        return OrderConnectionType(
            nodes=nodes, page_info=PageInfoType(has_next_page=page.has_next, end_cursor=end_cursor))
