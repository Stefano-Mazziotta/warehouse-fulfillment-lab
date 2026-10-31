"""The whole order-to-shipment flow through GraphQL only, and every retry of it."""
from api_support import seed_stock

CREATE = """mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId warehouseId status } } }"""
ORDER_INPUT = {"orderId": "o1", "warehouseId": "w1", "lines": [
    {"lineId": "l1", "sku": "sku", "quantity": 3}, {"lineId": "l2", "sku": "sku", "quantity": 2}]}


def transition(lab, mutation, order_id="o1"):
    return lab.ok(f'mutation {{ {mutation}(orderId: "{order_id}") {{ order {{ status }} }} }}')[mutation]["order"]["status"]


def reservations(lab):
    return lab.ok("""{ order(orderId: "o1") { reservations {
        lineId sku warehouseId locationId quantity pickedQuantity } } }""")["order"]["reservations"]


def stock(reservation):
    return {key: reservation[key] for key in ("sku", "warehouseId", "locationId")}


def test_full_flow_from_create_to_shipped_through_graphql(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=2, b=3)

    created = lab.ok(CREATE, {"input": ORDER_INPUT})["createOrder"]["order"]
    assert created == {"orderId": "o1", "warehouseId": "w1", "status": "CREATED"}
    assert transition(lab, "allocateInventory") == "ALLOCATED"
    assert transition(lab, "startPicking") == "PICKING"

    held = reservations(lab)
    assert sum(item["quantity"] for item in held) == 5
    for item in held:
        picked = lab.ok("""mutation($input: RecordPickInput!) { recordPick(input: $input) {
            reservation { pickedQuantity } } }""", {"input": {
            "orderId": "o1", "lineId": item["lineId"], "stock": stock(item),
            "pickedQuantity": item["quantity"]}})
        assert picked["recordPick"]["reservation"]["pickedQuantity"] == item["quantity"]
    assert transition(lab, "completePicking") == "PICKED"

    package = lab.ok("""mutation($input: AddPackageInput!) { addPackage(input: $input) {
        package { packageId weightGrams contents { lineId quantity } } } }""", {"input": {
        "orderId": "o1", "packageId": "box-1", "weightGrams": 900, "lengthMm": 300,
        "widthMm": 200, "heightMm": 100,
        "contents": [{"lineId": i["lineId"], "stock": stock(i), "quantity": i["quantity"]} for i in held]}})
    assert package["addPackage"]["package"]["packageId"] == "box-1"
    assert transition(lab, "finishPacking") == "PACKED"

    shipment = lab.ok("""mutation { shipOrder(orderId: "o1") { shipment {
        status trackingNumber packageIds } } }""")["shipOrder"]["shipment"]
    assert shipment["status"] == "SHIPPED"
    assert shipment["trackingNumber"].startswith("FAKE-")
    assert shipment["packageIds"] == ["box-1"]

    final = lab.ok("""{ order(orderId: "o1") { status lines { lineId sku quantity }
        packages { packageId } shipment { status } } }""")["order"]
    assert final["status"] == "SHIPPED"
    assert [line["lineId"] for line in final["lines"]] == ["l1", "l2"]
    assert final["packages"] == [{"packageId": "box-1"}]
    assert final["shipment"] == {"status": "SHIPPED"}

    balance = lab.ok("""{ inventoryBalance(sku: "sku", warehouseId: "w1", locationId: "a") {
        onHand allocated picked available } }""")["inventoryBalance"]
    assert balance == {"onHand": 0, "allocated": 0, "picked": 0, "available": 0}


def test_every_mutation_is_safe_to_retry(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=5)
    order = {"orderId": "o1", "warehouseId": "w1", "lines": [{"lineId": "l1", "sku": "sku", "quantity": 2}]}

    assert lab.ok(CREATE, {"input": order}) == lab.ok(CREATE, {"input": order})
    assert transition(lab, "allocateInventory") == transition(lab, "allocateInventory") == "ALLOCATED"
    assert transition(lab, "startPicking") == transition(lab, "startPicking") == "PICKING"

    held = reservations(lab)[0]
    pick = {"input": {"orderId": "o1", "lineId": "l1", "stock": stock(held), "pickedQuantity": 2}}
    record = """mutation($input: RecordPickInput!) { recordPick(input: $input) { reservation { pickedQuantity } } }"""
    assert lab.ok(record, pick) == lab.ok(record, pick)
    assert lab.ok("""{ inventoryBalance(sku: "sku", warehouseId: "w1", locationId: "a") { picked } }""") == {
        "inventoryBalance": {"picked": 2}}

    assert transition(lab, "completePicking") == transition(lab, "completePicking") == "PICKED"
    add = """mutation($input: AddPackageInput!) { addPackage(input: $input) { package { packageId } } }"""
    box = {"input": {"orderId": "o1", "packageId": "box-1", "weightGrams": 1, "lengthMm": 1, "widthMm": 1,
                     "heightMm": 1, "contents": [{"lineId": "l1", "stock": stock(held), "quantity": 2}]}}
    assert lab.ok(add, box) == lab.ok(add, box)
    assert transition(lab, "finishPacking") == transition(lab, "finishPacking") == "PACKED"

    ship = 'mutation { shipOrder(orderId: "o1") { shipment { status trackingNumber } } }'
    first, second = lab.ok(ship), lab.ok(ship)
    assert first == second and first["shipOrder"]["shipment"]["status"] == "SHIPPED"
    reconcile = 'mutation { reconcileShipment(orderId: "o1") { shipment { status trackingNumber } } }'
    assert lab.ok(reconcile)["reconcileShipment"] == first["shipOrder"]
    assert lab.ok("""{ inventoryBalance(sku: "sku", warehouseId: "w1", locationId: "a") { onHand } }""") == {
        "inventoryBalance": {"onHand": 3}}


def test_cancel_order_is_idempotent_and_releases_stock(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=5)
    lab.ok(CREATE, {"input": {**ORDER_INPUT, "lines": [{"lineId": "l1", "sku": "sku", "quantity": 4}]}})
    transition(lab, "allocateInventory")
    assert transition(lab, "cancelOrder") == transition(lab, "cancelOrder") == "CANCELLED"
    assert lab.ok("""{ inventoryBalance(sku: "sku", warehouseId: "w1", locationId: "a") {
        allocated available } }""") == {"inventoryBalance": {"allocated": 0, "available": 5}}


def test_later_mutation_fields_in_one_operation_see_earlier_writes(lab):
    seed_stock(lab.engine, "owner", "sku", "w1", a=2)
    lab.ok(CREATE, {"input": {"orderId": "o1", "warehouseId": "w1", "lines": [
        {"lineId": "l1", "sku": "sku", "quantity": 2}]}})
    transition(lab, "allocateInventory")
    item = reservations(lab)[0]

    data = lab.ok("""mutation($input: RecordPickInput!) {
        before: startPicking(orderId: "o1") { order { reservations { pickedQuantity } } }
        pick: recordPick(input: $input) { reservation { pickedQuantity } }
        after: completePicking(orderId: "o1") { order { reservations { pickedQuantity } } }
    }""", {"input": {"orderId": "o1", "lineId": item["lineId"], "stock": stock(item), "pickedQuantity": 2}})

    assert data["before"]["order"]["reservations"][0]["pickedQuantity"] == 0
    assert data["pick"]["reservation"]["pickedQuantity"] == 2
    assert data["after"]["order"]["reservations"][0]["pickedQuantity"] == 2
