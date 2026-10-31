import json
import logging
import time
from collections.abc import Callable
from urllib.parse import quote

import valkey

from orders.application.cache_unavailable import CacheUnavailable
from orders.application.order_summary import OrderSummary
from orders.domain import OrderStatus


logger = logging.getLogger("orders.cache")


class ValkeyOrderSummaryCache:
    """Entries expire on their own, so a lost invalidation can only be stale for `ttl_seconds`."""

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int,
        key_prefix: str = "lab:order-summary:",
        timeout_seconds: float = 0.2,
        clock: Callable[[], float] = time.monotonic,
        log_interval_seconds: float = 5.0,
    ) -> None:
        # Short timeouts matter more than retries: a slow cache must cost less than the query it saves.
        self._client = valkey.Valkey.from_url(
            url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
            retry_on_timeout=False,
        )
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix
        self._clock = clock
        self._log_interval_seconds = log_interval_seconds
        self._next_log_at = 0.0

    def get(self, client_id: str, order_id: str) -> OrderSummary | None:
        payload = self._call("get", self._client.get, self._key(client_id, order_id))
        if payload is None:
            return None
        try:
            data = json.loads(payload)
            return OrderSummary(data["order_id"], data["warehouse_id"], OrderStatus(data["status"]))
        except (ValueError, KeyError, TypeError):
            # A payload we cannot read is a miss; the caller will overwrite it from PostgreSQL.
            return None

    def put(self, client_id: str, summary: OrderSummary) -> None:
        payload = json.dumps({
            "order_id": summary.order_id,
            "warehouse_id": summary.warehouse_id,
            "status": summary.status.value,
        })
        self._call(
            "put", self._client.set, self._key(client_id, summary.order_id), payload, ex=self._ttl_seconds)

    def invalidate(self, client_id: str, order_id: str) -> None:
        self._call("invalidate", self._client.delete, self._key(client_id, order_id))

    def _key(self, client_id: str, order_id: str) -> str:
        # Owner is part of the key, mirroring the owner-scoped queries: no cross-client hits.
        # Each part is percent-encoded so ":" can only be the separator; otherwise owner "a:b"
        # + order "c" would share a key with owner "a" + order "b:c".
        return f"{self._key_prefix}{quote(client_id, safe='')}:{quote(order_id, safe='')}"

    def _call(self, name: str, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (valkey.ValkeyError, OSError) as error:
            self._warn(name, error)
            raise CacheUnavailable(str(error)) from error

    def _warn(self, name: str, error: Exception) -> None:
        # Same size as the read path's cooldown, so a dead server logs once per window; the
        # throttle also covers invalidations, which have no cooldown of their own.
        now = self._clock()
        if now < self._next_log_at:
            return
        self._next_log_at = now + self._log_interval_seconds
        logger.warning("cache unavailable; reads fall back to PostgreSQL",
                       extra={"operation": name, "error_type": type(error).__name__})
