from collections.abc import Iterator
from contextlib import contextmanager

from inventory.domain import InventoryError
from orders.domain import OrderError
from shipping.domain.shipping_error import ShippingError

from .bad_user_input import BadUserInput


@contextmanager
def invalid_input() -> Iterator[None]:
    """Domain validation that fires while building commands from inputs is a client mistake.

    The same exception types raised later, inside a use case, mean a state conflict.
    """
    try:
        yield
    except (OrderError, InventoryError, ShippingError) as error:
        raise BadUserInput(str(error)) from error
