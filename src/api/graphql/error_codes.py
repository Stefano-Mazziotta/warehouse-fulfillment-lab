"""The single table that turns application and domain failures into GraphQL error codes."""

from inventory.application.inventory_not_found import InventoryNotFound
from inventory.domain import InventoryError
from orders.application.order_not_found import OrderNotFound
from orders.domain import OrderError
from shipping.domain.shipping_error import ShippingError

from .bad_user_input import BadUserInput

BAD_USER_INPUT = "BAD_USER_INPUT"
NOT_FOUND = "NOT_FOUND"
CONFLICT = "CONFLICT"
INTERNAL = "INTERNAL"

# Anything absent from this table is unexpected and must never leak its message.
SAFE_CODES: tuple[tuple[tuple[type[BaseException], ...], str], ...] = (
    ((BadUserInput,), BAD_USER_INPUT),
    ((OrderNotFound, InventoryNotFound), NOT_FOUND),
    ((OrderError, ShippingError, InventoryError), CONFLICT),
)


def code_for(error: BaseException) -> str:
    for types, code in SAFE_CODES:
        if isinstance(error, types):
            return code
    return INTERNAL
