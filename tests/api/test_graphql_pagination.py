import base64

import pytest

from api_support import seed_stock

CREATE = """mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId } } }"""
PAGE = """query($first: Int, $after: String) { orders(first: $first, after: $after) {
    nodes { orderId } pageInfo { hasNextPage endCursor } } }"""


def create(lab, order_id, client="owner"):
    lab.ok(CREATE, {"input": {"orderId": order_id, "warehouseId": "w1",
                              "lines": [{"lineId": "l1", "sku": "sku", "quantity": 1}]}}, client)


def page(lab, first=None, after=None, client="owner"):
    return lab.ok(PAGE, {"first": first, "after": after}, client)["orders"]


@pytest.fixture
def five_orders(lab):
    for number in range(1, 6):
        create(lab, f"o{number}")
    create(lab, "zz-other-client", client="other")


def ids(result):
    return [node["orderId"] for node in result["nodes"]]


def test_pages_walk_the_whole_list_in_stable_order(lab, five_orders):
    first = page(lab, first=2)
    assert ids(first) == ["o1", "o2"] and first["pageInfo"]["hasNextPage"] is True
    second = page(lab, first=2, after=first["pageInfo"]["endCursor"])
    assert ids(second) == ["o3", "o4"] and second["pageInfo"]["hasNextPage"] is True
    last = page(lab, first=2, after=second["pageInfo"]["endCursor"])
    assert ids(last) == ["o5"] and last["pageInfo"]["hasNextPage"] is False


def test_exact_fit_page_reports_no_next_page(lab, five_orders):
    result = page(lab, first=5)
    assert len(ids(result)) == 5 and result["pageInfo"]["hasNextPage"] is False


def test_empty_list_has_no_cursor(lab):
    assert page(lab) == {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}


def test_new_rows_before_the_cursor_do_not_shift_later_pages(lab, five_orders):
    first = page(lab, first=2)
    create(lab, "o0")  # sorts before the cursor: offset paging would repeat o2 here
    second = page(lab, first=2, after=first["pageInfo"]["endCursor"])
    assert ids(second) == ["o3", "o4"]


def test_default_page_size_applies(lab):
    for number in range(25):
        create(lab, f"o{number:02d}")
    assert len(ids(page(lab))) == 20


def test_page_size_boundaries(lab):
    assert lab.error_codes(PAGE, {"first": 51}) == ["BAD_USER_INPUT"]
    assert lab.error_codes(PAGE, {"first": 0}) == ["BAD_USER_INPUT"]
    assert lab.error_codes(PAGE, {"first": -1}) == ["BAD_USER_INPUT"]
    assert page(lab, first=50)["nodes"] == []


@pytest.mark.parametrize("cursor", [
    "not-base64!!", "", base64.urlsafe_b64encode(b"o1").decode(),
    base64.urlsafe_b64encode(b"order:").decode()])
def test_bad_cursor_is_rejected(lab, cursor):
    assert lab.error_codes(PAGE, {"first": 2, "after": cursor}) == ["BAD_USER_INPUT"]


def test_cursor_from_another_client_reveals_nothing(lab, five_orders):
    foreign = page(lab, first=1, client="other")["pageInfo"]["endCursor"]
    assert page(lab, first=5, after=foreign) == {
        "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}


def test_pagination_ignores_other_clients(lab, five_orders):
    seed_stock(lab.engine, "other", "sku", "w1", a=1)
    assert "zz-other-client" not in ids(page(lab, first=50))
