"""Transport contracts proven without PostgreSQL: input parsing, headers and query limits.

Every request here is rejected before a use case runs, so the services are fakes that
fail the test if they are called.
"""
from api_support import build_adapter_lab

from test_sales_channel_webhook import event

FULL_PAGE = """query($first: Int) { orders(first: $first) { nodes {
    orderId lines { lineId sku quantity }
    reservations { lineId sku warehouseId locationId quantity pickedQuantity }
    packages { packageId contents { lineId sku quantity } }
    shipment { attemptId status trackingNumber packageIds } }
    pageInfo { hasNextPage endCursor } } }"""


def test_invalid_webhook_payloads_are_rejected_before_the_use_case(adapter_lab):
    broken = event()
    del broken["order"]["lines"]
    naive_time = event()
    naive_time["order"]["updated_at"] = "2026-10-01T12:00:00"
    for body in (broken, naive_time, {"order": event()["order"]}, [], "text",
                 {**event(), "event_id": ""}, {**event(), "order": "x"}):
        response = adapter_lab.client.post("/webhooks/sales-channel", json=body)
        assert response.status_code == 400, body
        assert "error" in response.get_json()
    malformed = adapter_lab.client.post(
        "/webhooks/sales-channel", data="{", content_type="application/json")
    assert malformed.status_code == 400


def test_missing_client_header_is_rejected_before_execution(adapter_lab):
    response = adapter_lab.client.post("/graphql", json={"query": "{ orders { nodes { orderId } } }"})
    assert response.status_code == 401
    assert response.get_json()["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


def test_deeply_nested_query_is_rejected_by_the_depth_rule(adapter_lab):
    body = adapter_lab.gql(
        "{ __schema { types { fields { type { ofType { ofType { ofType { name } } } } } } } }")
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_DEEP"


def test_expensive_page_is_rejected_by_the_complexity_rule(adapter_lab):
    assert adapter_lab.error_codes(FULL_PAGE, {"first": 50}) == ["QUERY_TOO_COMPLEX"]


def test_aliases_cannot_multiply_cost_past_the_limit(adapter_lab):
    aliased = " ".join(f"a{n}: orders(first: 50) {{ nodes {{ orderId lines {{ sku }} }} }}" for n in range(6))
    assert adapter_lab.error_codes("{ " + aliased + " }") == ["QUERY_TOO_COMPLEX"]


def test_fragment_cycles_are_rejected_without_hanging(adapter_lab):
    cyclic = "{ orders { nodes { ...A } } } fragment A on Order { orderId ...B } fragment B on Order { ...A }"
    assert "errors" in adapter_lab.gql(cyclic)


def test_limits_come_from_configuration():
    strict = build_adapter_lab(max_query_complexity=5)
    assert strict.error_codes("{ orders(first: 2) { nodes { orderId lines { sku } } } }") == ["QUERY_TOO_COMPLEX"]
