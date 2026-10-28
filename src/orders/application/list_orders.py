from .order_page import OrderPage
from .order_queries import OrderQueries


class ListOrders:

    def __init__(self, queries: OrderQueries) -> None:
        self._queries = queries

    def execute(self, client_id: str, after_order_id: str | None, limit: int) -> OrderPage:
        # One extra row tells us whether another page exists without a COUNT.
        rows = self._queries.list_summaries(client_id, after_order_id, limit + 1)
        return OrderPage(rows[:limit], has_next=len(rows) > limit)
