import time
from collections.abc import Callable, Sequence

from orders.domain import OrderLine, Reservation

from .order_queries import OrderQueries
from .order_summary import OrderSummary
from .order_summary_cache import OrderSummaryCache


class CachingOrderQueries:
    """Cache-aside over the order read port: only `get_summary` is cached.

    Lists and batches are not: any new or changed order alters some page, so keeping them
    fresh needs fan-out invalidation that the lab's short TTL does not justify.
    """

    def __init__(
        self,
        queries: OrderQueries,
        cache: OrderSummaryCache,
        *,
        clock: Callable[[], float] = time.monotonic,
        cooldown_seconds: float = 5.0,
    ) -> None:
        self._queries = queries
        self._cache = cache
        self._clock = clock
        self._cooldown_seconds = cooldown_seconds
        self._skip_cache_until = 0.0

    def get_summary(self, client_id: str, order_id: str) -> OrderSummary | None:
        cached = self._attempt(lambda: self._cache.get(client_id, order_id))
        if cached is not None:
            return cached
        summary = self._queries.get_summary(client_id, order_id)
        if summary is not None:
            self._attempt(lambda: self._cache.put(client_id, summary))
        return summary

    def list_summaries(
        self, client_id: str, after_order_id: str | None, limit: int
    ) -> tuple[OrderSummary, ...]:
        return self._queries.list_summaries(client_id, after_order_id, limit)

    def lines_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[OrderLine, ...]]:
        return self._queries.lines_for(client_id, order_ids)

    def reservations_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[Reservation, ...]]:
        return self._queries.reservations_for(client_id, order_ids)

    def _attempt(self, operation):
        """Best effort: the cache is an optimization, so any failure degrades to a miss.

        Catching Exception is deliberate (a serialization bug must not take reads down too).
        After a failure the cache is skipped for a cooldown, so a down server costs one
        timeout per window instead of one per request.
        """
        if self._clock() < self._skip_cache_until:
            return None
        try:
            return operation()
        except Exception:
            self._skip_cache_until = self._clock() + self._cooldown_seconds
            return None
