from .order_not_found import OrderNotFound
from .order_queries import OrderQueries
from .order_summary import OrderSummary
from orders.domain import OrderKey


class GetOrderSummary:

    def __init__(self, queries: OrderQueries) -> None:
        self._queries = queries

    def execute(self, key: OrderKey) -> OrderSummary:
        summary = self._queries.get_summary(key.client_id, key.order_id)
        if summary is None:
            raise OrderNotFound(key)
        return summary
