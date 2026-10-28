"""Page assembly is application logic and needs no database or web framework."""
from orders.application.list_orders import ListOrders
from orders.application.order_summary import OrderSummary
from orders.domain import OrderStatus


class FakeQueries:
    def __init__(self, count):
        self.rows = [OrderSummary(f"o{n:02d}", "w1", OrderStatus.CREATED) for n in range(count)]
        self.requested = []

    def list_summaries(self, client_id, after_order_id, limit):
        self.requested.append(limit)
        rows = [row for row in self.rows if after_order_id is None or row.order_id > after_order_id]
        return tuple(rows[:limit])


def test_asks_for_one_extra_row_and_trims_it():
    queries = FakeQueries(5)
    page = ListOrders(queries).execute("c", None, 2)
    assert queries.requested == [3]
    assert [item.order_id for item in page.items] == ["o00", "o01"] and page.has_next


def test_exact_last_page_has_no_next():
    page = ListOrders(FakeQueries(2)).execute("c", None, 2)
    assert len(page.items) == 2 and not page.has_next


def test_cursor_is_passed_through():
    page = ListOrders(FakeQueries(4)).execute("c", "o01", 5)
    assert [item.order_id for item in page.items] == ["o02", "o03"] and not page.has_next
