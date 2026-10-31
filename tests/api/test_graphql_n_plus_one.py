"""DataLoader keeps statement count constant per page; the counter itself must detect O(n)."""
from sqlalchemy import event

from api_support import ship_through_services
from orders.domain import OrderKey

NESTED_PAGE = """query($first: Int) { orders(first: $first) { nodes {
    orderId status
    lines { lineId sku quantity }
    reservations { lineId locationId quantity pickedQuantity }
    packages { packageId contents { lineId quantity } }
    shipment { status trackingNumber } } } }"""


class StatementCounter:
    def __init__(self, engine):
        self.engine, self.statements = engine, []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_):
        event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, connection, cursor, statement, *_):
        self.statements.append(statement)


def seed_orders(lab, count):
    for number in range(count):
        ship_through_services(lab, "owner", f"o{number:02d}", f"sku-{number:02d}")


def count_page_statements(lab, first):
    with StatementCounter(lab.engine) as counter:
        data = lab.ok(NESTED_PAGE, {"first": first})
    assert len(data["orders"]["nodes"]) == first
    assert all(node["shipment"]["status"] == "SHIPPED" and node["packages"] for node in data["orders"]["nodes"])
    return len(counter.statements)


def test_statements_per_page_do_not_grow_with_the_number_of_orders(lab):
    seed_orders(lab, 20)
    lab.ok(NESTED_PAGE, {"first": 1})  # warm connection-level setup so it is not counted

    small, large = count_page_statements(lab, 3), count_page_statements(lab, 20)

    assert small == large
    # page + lines + reservations + packages(+items) + attempts(+packages) = 7
    assert large <= 8


def test_statement_counter_detects_a_per_order_query_pattern(lab):
    seed_orders(lab, 5)
    with StatementCounter(lab.engine) as counter:
        for number in range(5):
            lab.services.get_order.execute(OrderKey("owner", f"o{number:02d}"))
    assert len(counter.statements) >= 5
