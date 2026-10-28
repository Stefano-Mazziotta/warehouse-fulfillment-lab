from typing import Protocol

from .order_summary import OrderSummary


class OrderSummaryCache(Protocol):
    """Cache-aside storage for read-side order headers. Never a source of truth.

    Every method may raise CacheUnavailable; no caller may depend on an entry being present.
    """

    def get(self, client_id: str, order_id: str) -> OrderSummary | None: ...

    def put(self, client_id: str, summary: OrderSummary) -> None: ...

    def invalidate(self, client_id: str, order_id: str) -> None: ...
