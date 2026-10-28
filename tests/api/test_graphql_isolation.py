"""X-Client-Id is a stand-in for authentication; everything is scoped to it."""
import pytest

from api_support import seed_stock, ship_through_services

CREATE = """mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId } } }"""
ORDER = {"orderId": "o1", "warehouseId": "w1", "lines": [{"lineId": "l1", "sku": "sku", "quantity": 1}]}
STOCK = {"sku": "sku", "warehouseId": "w1", "locationId": "a"}

FOREIGN_MUTATIONS = [
    'mutation { allocateInventory(orderId: "o1") { order { status } } }',
    'mutation { cancelOrder(orderId: "o1") { order { status } } }',
    'mutation { startPicking(orderId: "o1") { order { status } } }',
    'mutation { completePicking(orderId: "o1") { order { status } } }',
    'mutation { finishPacking(orderId: "o1") { order { status } } }',
    'mutation { shipOrder(orderId: "o1") { shipment { status } } }',
    'mutation { reconcileShipment(orderId: "o1") { shipment { status } } }',
    """mutation { recordPick(input: {orderId: "o1", lineId: "l1", pickedQuantity: 1,
        stock: {sku: "sku", warehouseId: "w1", locationId: "a"}}) { reservation { quantity } } }""",
    """mutation { addPackage(input: {orderId: "o1", packageId: "p", weightGrams: 1, lengthMm: 1,
        widthMm: 1, heightMm: 1, contents: [{lineId: "l1", quantity: 1,
        stock: {sku: "sku", warehouseId: "w1", locationId: "a"}}]}) { package { packageId } } }""",
]


def test_missing_client_header_is_rejected_before_execution(lab):
    response = lab.client.post("/graphql", json={"query": "{ orders { nodes { orderId } } }"})
    assert response.status_code == 401
    assert response.get_json()["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"


def test_blank_client_header_is_rejected(lab):
    assert lab.gql("{ orders { nodes { orderId } } }", client_id="   ")["errors"][0][
        "extensions"]["code"] == "UNAUTHENTICATED"


def test_another_client_cannot_read_an_order(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=1)
    lab.ok(CREATE, {"input": ORDER})
    body = lab.gql('{ order(orderId: "o1") { orderId lines { sku } } }', client_id="intruder")
    assert body["data"] == {"order": None}
    assert body["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    assert lab.ok("{ orders { nodes { orderId } } }", client_id="intruder") == {
        "orders": {"nodes": []}}


@pytest.mark.parametrize("mutation", FOREIGN_MUTATIONS)
def test_another_client_cannot_mutate_an_order(lab, mutation):
    seed_stock(lab.engine, "owner", "sku", "w1", a=1)
    lab.ok(CREATE, {"input": ORDER})
    assert lab.error_codes(mutation, client_id="intruder") == ["NOT_FOUND"]
    assert lab.ok('{ order(orderId: "o1") { status } }') == {"order": {"status": "CREATED"}}


def test_another_client_cannot_read_stock(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=1)
    query = '{ inventoryBalance(sku: "sku", warehouseId: "w1", locationId: "a") { onHand } }'
    assert lab.ok(query) == {"inventoryBalance": {"onHand": 1}}
    assert lab.error_codes(query, client_id="intruder") == ["NOT_FOUND"]


def test_same_order_id_under_two_clients_are_two_orders(lab):
    for client in ("owner", "other"):
        seed_stock(lab.engine, client, "sku", "w1", a=1)
        lab.ok(CREATE, {"input": ORDER}, client_id=client)
    lab.ok('mutation { allocateInventory(orderId: "o1") { order { status } } }')
    assert lab.ok('{ order(orderId: "o1") { status } }', client_id="other") == {"order": {"status": "CREATED"}}


def test_foreign_order_hidden_even_with_nested_batches(lab):
    ship_through_services(lab, "owner", "o1", "sku-1")
    body = lab.gql("""{ orders { nodes { orderId packages { packageId } shipment { status } } } }""",
                   client_id="intruder")
    assert body["data"] == {"orders": {"nodes": []}}
