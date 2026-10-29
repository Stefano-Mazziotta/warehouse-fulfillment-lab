from demo_state import broker_view, cache_view, postgres_view, projection_view

SNAPSHOT = {
    "order": {"status": "ALLOCATED"},
    "stock": {"on_hand": 10, "allocated": 3, "picked": 0, "packed": 0},
    "reservations": [{"line_id": "l1", "location_id": "BIN-A1", "quantity": 3, "picked_quantity": 0}],
    "packages": [],
    "attempt": None,
    "outbox": [{"event_type": "OrderAllocated", "status": "PENDING", "attempt_count": 0}],
}


def test_available_is_derived_not_stored():
    text = postgres_view(SNAPSHOT, ("stock",))

    assert "available" in text
    assert text.splitlines()[-1].split()[-1] == "7"


def test_only_the_requested_sections_are_shown():
    text = postgres_view(SNAPSHOT, ("order", "outbox"))

    assert "ALLOCATED" in text and "OrderAllocated" in text
    assert "on_hand" not in text


def test_a_missing_shipping_attempt_is_explicit():
    assert "no shipping attempt" in postgres_view(SNAPSHOT, ("attempt",))


def test_projection_view_distinguishes_absent_from_present():
    assert "no item" in projection_view(None)
    shown = projection_view({"status": "SHIPPED", "stage": 4, "tracking_number": "FAKE-1", "package_count": 1})
    assert "SHIPPED" in shown and "FAKE-1" in shown and "4" in shown


def test_cache_view_reports_presence_ttl_and_hit_delta():
    text = cache_view({"exists": True, "ttl": 29}, hits_delta=1)

    assert "present" in text and "29" in text and "+1" in text
    assert "absent" in cache_view({"exists": False, "ttl": None})


def test_broker_view_names_the_queue_counters():
    text = broker_view({"processed": 3, "ready": 0, "consumers": 1})

    assert "orders.projection" in text and "processed=3" in text and "consumers=1" in text
