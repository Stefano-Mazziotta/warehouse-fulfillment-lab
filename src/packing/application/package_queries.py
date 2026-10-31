from typing import Protocol, Sequence

from packing.domain.package import Package


class PackageQueries(Protocol):
    """Owner-scoped batch read: packages with contents for many orders in a constant number of queries."""

    def packages_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, tuple[Package, ...]]: ...
