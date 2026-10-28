from collections.abc import Callable
from typing import Any

from orders.domain import OrderKey

from .order_summary_cache import OrderSummaryCache


class InvalidatingUseCase:
    """Runs a state-changing use case, then drops the order's cached summary.

    Invalidation is best effort and follows the commit, so it narrows the stale window but
    cannot close it (a concurrent reader can repopulate the old value); the TTL is the backstop.
    """

    def __init__(
        self, use_case: Any, cache: OrderSummaryCache, key_of: Callable[..., OrderKey]
    ) -> None:
        self._use_case = use_case
        self._cache = cache
        self._key_of = key_of

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._use_case.execute(*args, **kwargs)
        finally:
            # Also on failure: a lost response or timeout may follow a committed change.
            self._invalidate(self._key_of(*args, **kwargs))

    def _invalidate(self, key: OrderKey) -> None:
        try:
            self._cache.invalidate(key.client_id, key.order_id)
        except Exception:
            pass
