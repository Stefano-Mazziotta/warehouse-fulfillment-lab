from dataclasses import dataclass

from .order_error import OrderError


@dataclass(frozen=True)
class OrderLine:

    line_id: str
    sku: str
    quantity: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.line_id, self.sku)
        ):
            raise OrderError("Identifiers must be nonempty strings")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise OrderError("Quantity must be a positive integer")
