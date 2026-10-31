from collections.abc import Sequence

from orders.application.cache_unavailable import CacheUnavailable
from orders.application.order_summary import OrderSummary
from orders.domain import OrderLine, Reservation


class FakeOrderSummaryCache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], OrderSummary] = {}
        self.calls: list[tuple[str, str, str]] = []

    def get(self, client_id, order_id):
        self.calls.append(("get", client_id, order_id))
        return self.entries.get((client_id, order_id))

    def put(self, client_id, summary):
        self.calls.append(("put", client_id, summary.order_id))
        self.entries[(client_id, summary.order_id)] = summary

    def invalidate(self, client_id, order_id):
        self.calls.append(("invalidate", client_id, order_id))
        self.entries.pop((client_id, order_id), None)


class DownCache:
    """Every operation fails the way an unreachable Valkey does."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or CacheUnavailable("connection refused")
        self.attempts = 0

    def _fail(self, *args):
        self.attempts += 1
        raise self.error

    get = put = invalidate = _fail


class SwitchableCache(FakeOrderSummaryCache):
    def __init__(self) -> None:
        super().__init__()
        self.down = False

    def _check(self):
        if self.down:
            raise CacheUnavailable("connection refused")

    def get(self, client_id, order_id):
        self._check()
        return super().get(client_id, order_id)

    def put(self, client_id, summary):
        self._check()
        super().put(client_id, summary)

    def invalidate(self, client_id, order_id):
        self._check()
        super().invalidate(client_id, order_id)


class CountingQueries:
    """Stands in for PostgreSQL: owns the truth and counts how often it is asked."""

    def __init__(self, summaries: Sequence[OrderSummary] = ()) -> None:
        self.rows = {s.order_id: s for s in summaries}
        self.get_summary_calls = 0

    def get_summary(self, client_id, order_id):
        self.get_summary_calls += 1
        return self.rows.get(order_id)

    def list_summaries(self, client_id, after_order_id, limit):
        return tuple(s for s in sorted(self.rows.values(), key=lambda s: s.order_id)
                     if after_order_id is None or s.order_id > after_order_id)[:limit]

    def lines_for(self, client_id, order_ids) -> dict[str, tuple[OrderLine, ...]]:
        return {}

    def reservations_for(self, client_id, order_ids) -> dict[str, tuple[Reservation, ...]]:
        return {}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now
