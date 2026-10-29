"""What the demo script needs from the running lab. Real adapters live in demo_gateways.py."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from demo_ids import RunIds

# Polls `predicate` until it is true or `timeout_seconds` pass; returns whether it became true.
Wait = Callable[[Callable[[], bool], float], bool]


class Api(Protocol):
    def graphql(self, query: str, variables: dict | None = None, *, request_id: str | None = None) -> dict:
        """Returns the response `data`; raises on any GraphQL error."""


class Truth(Protocol):
    def seed_stock(self, ids: RunIds, on_hand: int) -> None: ...

    def snapshot(self, ids: RunIds) -> dict:
        """Keys: order, stock, reservations, packages, attempt, outbox (rows as plain dicts)."""


class Projection(Protocol):
    def item(self, ids: RunIds) -> dict | None: ...


class Cache(Protocol):
    def entry(self, ids: RunIds) -> dict: ...

    def hits(self) -> int: ...


class Broker(Protocol):
    def queue_stats(self, ids: RunIds) -> dict: ...


class Relay(Protocol):
    def start(self) -> None: ...


class Logs(Protocol):
    def find_error(self, request_id: str) -> dict | None: ...


class ErrorApi(Protocol):
    def trigger(self, ids: RunIds) -> tuple[int, str, str]:
        """Provokes an unhandled server error; returns HTTP status, echoed request id, client-visible error."""


@dataclass(frozen=True)
class Ports:
    api: Api
    truth: Truth
    projection: Projection
    cache: Cache
    broker: Broker
    relay: Relay
    logs: Logs
    error_api: ErrorApi
    wait: Wait
