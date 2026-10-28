"""Depth and cost limits reject abusive queries before any resolver runs."""
from api_support import build_lab

FULL_PAGE = """query($first: Int) { orders(first: $first) { nodes {
    orderId warehouseId status
    lines { lineId sku quantity }
    reservations { lineId sku warehouseId locationId quantity pickedQuantity }
    packages { packageId weightGrams lengthMm widthMm heightMm
        contents { lineId sku warehouseId locationId quantity } }
    shipment { attemptId status trackingNumber packageIds } }
    pageInfo { hasNextPage endCursor } } }"""


def test_deeply_nested_query_is_rejected_with_a_clear_code(lab):
    body = lab.gql("{ __schema { types { fields { type { ofType { ofType { ofType { name } } } } } } } }")
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_DEEP"
    assert "maximum depth of 7" in body["errors"][0]["message"]
    assert "data" not in body or body["data"] is None


def test_realistic_nested_query_is_within_the_depth_limit(lab):
    assert lab.ok("{ orders { nodes { packages { contents { sku } } } } }") == {"orders": {"nodes": []}}


def test_expensive_page_is_rejected_by_complexity(lab):
    body = lab.gql(FULL_PAGE, {"first": 50})
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert "1000" in body["errors"][0]["message"]


def test_same_shape_with_a_smaller_page_is_accepted(lab):
    assert lab.ok(FULL_PAGE, {"first": 20})["orders"]["nodes"] == []


def test_aliases_cannot_multiply_cost_past_the_limit(lab):
    aliased = " ".join(f"a{n}: orders(first: 50) {{ nodes {{ orderId lines {{ sku }} }} }}" for n in range(6))
    assert lab.error_codes("{ " + aliased + " }") == ["QUERY_TOO_COMPLEX"]


def test_fragments_count_toward_cost_and_cycles_do_not_hang(lab):
    cyclic = "{ orders { nodes { ...A } } } fragment A on Order { orderId ...B } fragment B on Order { ...A }"
    body = lab.gql(cyclic)
    assert "errors" in body


def test_limits_come_from_configuration(orders_database):
    strict = build_lab(orders_database, max_query_complexity=5)
    assert strict.error_codes("{ orders(first: 2) { nodes { orderId lines { sku } } } }") == ["QUERY_TOO_COMPLEX"]
