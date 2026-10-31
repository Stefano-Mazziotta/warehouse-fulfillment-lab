from datetime import datetime, timezone

from sqlalchemy import select

from integrations.infrastructure.integrations_schema import integration_events
from orders.infrastructure.order_schema import orders

WHEN = datetime(2026, 10, 1, 12, tzinfo=timezone.utc).isoformat()


def event(event_id="evt-1", *, version=1, quantity=2):
    return {"event_id": event_id, "order": {
        "client_id": "owner", "channel_order_id": "c1", "warehouse_id": "w1", "version": version,
        "updated_at": WHEN, "lines": [{"line_id": "l1", "sku": "sku", "quantity": quantity}]}}


def post(lab, body):
    return lab.client.post("/webhooks/sales-channel", json=body)


def stored_events(lab):
    with lab.engine.connect() as connection:
        return {row.id: row for row in connection.execute(select(integration_events))}


def order_ids(lab):
    with lab.engine.connect() as connection:
        return list(connection.scalars(select(orders.c.order_id)))


def test_valid_event_is_accepted_persisted_and_creates_the_order(lab):
    response = post(lab, event())
    assert response.status_code == 202
    assert response.get_json() == {"eventId": "evt-1", "outcome": "CREATED"}
    assert order_ids(lab) == ["c1"]
    assert stored_events(lab)["evt-1"].status == "PROCESSED"


def test_duplicate_event_id_is_harmless(lab):
    post(lab, event())
    again = post(lab, event())
    assert again.status_code == 202
    assert again.get_json()["outcome"] == "DUPLICATE_EVENT"
    assert order_ids(lab) == ["c1"] and len(stored_events(lab)) == 1


def test_conflicting_payload_is_persisted_as_failed_but_still_acknowledged(lab):
    post(lab, event("evt-1", version=1, quantity=2))
    response = post(lab, event("evt-2", version=2, quantity=9))
    assert response.status_code == 202
    assert response.get_json()["outcome"] == "CONFLICT"
    assert stored_events(lab)["evt-2"].status == "FAILED"  # raw event kept as evidence


def test_invalid_payloads_are_rejected_with_400_and_store_nothing(lab):
    broken = event()
    del broken["order"]["lines"]
    bad_quantity = event()
    bad_quantity["order"]["lines"][0]["quantity"] = 0
    naive_time = event()
    naive_time["order"]["updated_at"] = "2026-10-01T12:00:00"
    for body in (broken, bad_quantity, naive_time, {"order": event()["order"]}, [], "text",
                 {**event(), "event_id": ""}, {**event(), "order": "x"}):
        response = post(lab, body)
        assert response.status_code == 400, body
        assert "error" in response.get_json()
    not_json = lab.client.post("/webhooks/sales-channel", data="{", content_type="application/json")
    assert not_json.status_code == 400
    assert stored_events(lab) == {} and order_ids(lab) == []
