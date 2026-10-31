from dataclasses import dataclass

from .order_error import OrderError


@dataclass(frozen=True)
class OrderKey:
    """Owner-scoped order identity, independent of any database."""

    client_id: str
    order_id: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.client_id, self.order_id)
        ):
            raise OrderError("Identifiers must be nonempty strings")
