from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TypeVar

from strawberry.dataloader import DataLoader

from orders.domain import OrderLine, Reservation
from packing.domain.package import Package
from shipping.application.attempt_summary import AttemptSummary

from ..api_services import ApiServices

T = TypeVar("T")


def _batch(
    fetch: Callable[[Sequence[str]], Mapping[str, T]], empty: T
) -> Callable[[list[str]], Awaitable[list[T]]]:
    async def load(order_ids: list[str]) -> list[T]:
        # One query for every order that asked during this tick; missing orders get `empty`.
        found = fetch(order_ids)
        return [found.get(order_id, empty) for order_id in order_ids]

    return load


class RequestLoaders:
    """Loaders cache per instance, so they are created per request and scoped to one client.

    `reset` drops every cached value: a mutation changes what the batched reads would return.
    """

    def __init__(self, services: ApiServices, client_id: str) -> None:
        self._services = services
        self._client_id = client_id
        self.reset()

    def reset(self) -> None:
        services, client_id = self._services, self._client_id
        self.lines: DataLoader[str, tuple[OrderLine, ...]] = DataLoader(_batch(
            lambda ids: services.order_queries.lines_for(client_id, ids), ()))
        self.reservations: DataLoader[str, tuple[Reservation, ...]] = DataLoader(_batch(
            lambda ids: services.order_queries.reservations_for(client_id, ids), ()))
        self.packages: DataLoader[str, tuple[Package, ...]] = DataLoader(_batch(
            lambda ids: services.package_queries.packages_for(client_id, ids), ()))
        self.attempts: DataLoader[str, AttemptSummary | None] = DataLoader(_batch(
            lambda ids: services.attempt_queries.attempts_for(client_id, ids), None))
