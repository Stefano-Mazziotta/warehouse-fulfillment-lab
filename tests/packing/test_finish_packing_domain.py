from dataclasses import replace

import pytest

from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus

ORDER = Order(OrderKey(
    "owner",
    "order",
), "warehouse", (OrderLine(
    "a",
    "sku",
    3,
),), OrderStatus.PICKED)


def test_finish_packing_transitions_and_repeated_completion_is_noop():
    assert ORDER.finish_packing().status == OrderStatus.PACKED
    packed = ORDER.finish_packing()
    assert packed.finish_packing() is packed


@pytest.mark.parametrize(
    "status",
    [s for s in OrderStatus if s not in (OrderStatus.PICKED, OrderStatus.PACKED)],
)
def test_order_owns_packing_transition_guard(status):
    with pytest.raises(OrderError):
        replace(ORDER, status=status).finish_packing()

