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


class ExplodingReceiver:
    def execute(self, *_):
        raise RuntimeError("password=hunter2 host=db.internal")


def test_unexpected_webhook_failure_is_a_safe_json_500_with_a_request_id(caplog):
    lab = build_adapter_lab(receive=ExplodingReceiver())
    response = lab.client.post(
        "/webhooks/sales-channel", json=event(), headers={"X-Request-ID": "req-42"})
    assert response.status_code == 500
    assert response.mimetype == "application/json"
    assert response.get_json() == {"error": {"code": "INTERNAL", "message": "Internal server error",
                                             "requestId": "req-42"}}
    assert "hunter2" not in response.get_data(as_text=True)
    record = next(r for r in caplog.records if r.name == "api.errors")
    assert record.request_id == "req-42" and record.exc_info  # the original is logged server-side


def test_unknown_url_is_a_json_404(adapter_lab):
    response = adapter_lab.client.get("/nope")
    assert response.status_code == 404 and response.mimetype == "application/json"
    assert response.get_json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_is_a_json_405_that_keeps_the_allow_header(adapter_lab):
    response = adapter_lab.client.get("/webhooks/sales-channel")
    assert response.status_code == 405 and response.mimetype == "application/json"
    assert response.get_json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "POST" in response.headers["Allow"]


def test_oversized_body_is_a_json_413():
    lab = build_adapter_lab(max_request_bytes=100)
    response = lab.client.post("/webhooks/sales-channel", json=event())
    assert response.status_code == 413 and response.mimetype == "application/json"
    assert response.get_json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_a_generated_request_id_is_returned_when_the_caller_sends_none(adapter_lab):
    response = adapter_lab.client.get("/nope")
    assert response.get_json()["error"]["requestId"] == response.headers["X-Request-ID"]
