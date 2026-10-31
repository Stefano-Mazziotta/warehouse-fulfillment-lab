"""Domain failures become stable GraphQL error codes in exactly one place."""
import dataclasses

from api_support import attach, seed_stock

CREATE = """mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId } } }"""


def order(quantity=1, order_id="o1", line_id="l1"):
    return {"input": {"orderId": order_id, "warehouseId": "w1",
                      "lines": [{"lineId": line_id, "sku": "sku", "quantity": quantity}]}}


def test_unknown_order_is_not_found(lab):
    body = lab.gql('{ order(orderId: "missing") { orderId } }')
    assert body["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    assert lab.error_codes('mutation { startPicking(orderId: "missing") { order { status } } }') == ["NOT_FOUND"]


def test_invalid_state_transition_is_a_conflict(lab):
    lab.ok(CREATE, order())
    assert lab.error_codes('mutation { startPicking(orderId: "o1") { order { status } } }') == ["CONFLICT"]


def test_insufficient_stock_is_a_conflict(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=1)
    lab.ok(CREATE, order(quantity=2))
    assert lab.error_codes('mutation { allocateInventory(orderId: "o1") { order { status } } }') == ["CONFLICT"]
    assert lab.ok('{ order(orderId: "o1") { status } }') == {"order": {"status": "CREATED"}}


def test_conflicting_create_retry_is_a_conflict(lab):
    lab.ok(CREATE, order(quantity=1))
    assert lab.error_codes(CREATE, order(quantity=2)) == ["CONFLICT"]


def test_invalid_input_is_bad_user_input(lab):
    assert lab.error_codes(CREATE, order(quantity=0)) == ["BAD_USER_INPUT"]
    assert lab.error_codes(CREATE, order(order_id="  ")) == ["BAD_USER_INPUT"]
    assert lab.error_codes(CREATE, {"input": {**order()["input"], "lines": []}}) == ["BAD_USER_INPUT"]


def test_missing_input_field_is_rejected_by_the_schema(lab):
    body = lab.gql(CREATE, {"input": {"orderId": "o1"}})
    assert "errors" in body and body.get("data") is None


def test_unexpected_failures_are_masked_as_internal(lab):
    class Exploding:
        def execute(self, *_):
            raise RuntimeError("password=hunter2 host=db.internal")

    broken = attach(lab.engine, lab.config, dataclasses.replace(lab.services, start_picking=Exploding()))
    broken.ok(CREATE, order())
    response = broken.client.post("/graphql", headers={"X-Client-Id": "owner"}, json={
        "query": 'mutation { startPicking(orderId: "o1") { order { status } } }'})
    text = response.get_data(as_text=True)
    error = response.get_json()["errors"][0]
    assert error["extensions"]["code"] == "INTERNAL"
    assert error["message"] == "Internal server error"
    assert "hunter2" not in text and "Traceback" not in text and "RuntimeError" not in text
