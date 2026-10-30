"""Accepted-query proofs over PostgreSQL; rejections live in test_api_adapter_contract.py."""
FULL_PAGE = """query($first: Int) { orders(first: $first) { nodes {
    orderId warehouseId status
    lines { lineId sku quantity }
    reservations { lineId sku warehouseId locationId quantity pickedQuantity }
    packages { packageId weightGrams lengthMm widthMm heightMm
        contents { lineId sku warehouseId locationId quantity } }
    shipment { attemptId status trackingNumber packageIds } }
    pageInfo { hasNextPage endCursor } } }"""


def test_realistic_nested_query_is_within_the_depth_limit(lab):
    assert lab.ok("{ orders { nodes { packages { contents { sku } } } } }") == {"orders": {"nodes": []}}


def test_same_shape_with_a_smaller_page_is_accepted(lab):
    assert lab.ok(FULL_PAGE, {"first": 20})["orders"]["nodes"] == []
