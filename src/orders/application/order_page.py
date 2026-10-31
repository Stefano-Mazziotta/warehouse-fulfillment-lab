from dataclasses import dataclass

from .order_summary import OrderSummary


@dataclass(frozen=True)
class OrderPage:

    items: tuple[OrderSummary, ...]
    has_next: bool
