import json

import valkey

from orders.application.cache_unavailable import CacheUnavailable
from orders.application.order_summary import OrderSummary
from orders.domain import OrderStatus


class ValkeyOrderSummaryCache:
    """Entries expire on their own, so a lost invalidation can only be stale for `ttl_seconds`."""

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int,
        key_prefix: str = "lab:order-summary:",
        timeout_seconds: float = 0.2,
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

    def get(self, client_id: str, order_id: str) -> OrderSummary | None:
        payload = self._call(self._client.get, self._key(client_id, order_id))
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
            self._client.set, self._key(client_id, summary.order_id), payload, ex=self._ttl_seconds)

    def invalidate(self, client_id: str, order_id: str) -> None:
        self._call(self._client.delete, self._key(client_id, order_id))

    def _key(self, client_id: str, order_id: str) -> str:
        # Owner is part of the key, mirroring the owner-scoped queries: no cross-client hits.
        return f"{self._key_prefix}{client_id}:{order_id}"

    @staticmethod
    def _call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (valkey.ValkeyError, OSError) as error:
            raise CacheUnavailable(str(error)) from error
