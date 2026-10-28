from typing import Protocol, Sequence

from .attempt_summary import AttemptSummary


class AttemptQueries(Protocol):
    """Owner-scoped batch read of the single shipping attempt each order can have."""

    def attempts_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, AttemptSummary]: ...
