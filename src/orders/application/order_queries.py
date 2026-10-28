"""Read-side port: batch methods take many order IDs so one page costs a constant number of queries."""

from typing import Protocol, Sequence

from orders.domain import OrderLine, Reservation

from .order_summary import OrderSummary


class OrderQueries(Protocol):
    """Every method is scoped to one owner; a foreign order ID simply matches nothing."""

    def get_summary(self, client_id: str, order_id: str) -> OrderSummary | None: ...

    def list_summaries(
        self, client_id: str, after_order_id: str | None, limit: int
    ) -> tuple[OrderSummary, ...]:
        """Ascending order ID strictly after the cursor: a keyset page, stable under inserts."""

    def lines_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[OrderLine, ...]]: ...

    def reservations_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[Reservation, ...]]: ...
