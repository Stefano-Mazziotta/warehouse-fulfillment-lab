from datetime import datetime, timezone

import pytest

from demo_ids import new_run_ids
from demo_ports import Ports
from demo_script import DemoContext, DemoFailure, build_phases, run_phases

IDS = new_run_ids(datetime(2026, 10, 29, 10, 15, 30, tzinfo=timezone.utc), "ab12")
MUTATIONS = ("createOrder", "allocateInventory", "startPicking", "recordPick", "completePicking",
             "addPackage", "finishPacking", "shipOrder")


class FakeApi:
    def __init__(self):
        self.calls = []

    def graphql(self, query, variables=None, *, request_id=None):
        name = next((m for m in MUTATIONS if m + "(" in query), "order")
        self.calls.append((name, variables))
        if name == "order":
            return {"order": {"orderId": IDS.order_id, "status": "ALLOCATED", "reservations": [
                {"lineId": IDS.line_id, "sku": IDS.sku, "warehouseId": IDS.warehouse_id,
                 "locationId": IDS.location_id, "quantity": 3, "pickedQuantity": 0}]}}
        return {name: {}}


class FakeTruth:
    def __init__(self, relay):
        self.seeded = None
        self.relay = relay

    def seed_stock(self, ids, on_hand):
        self.seeded = (ids.client_id, on_hand)

    def snapshot(self, ids):
        return {"order": {"status": "ALLOCATED"},
                "stock": {"on_hand": 10, "allocated": 3, "picked": 0, "packed": 0},
                "reservations": [], "packages": [],
                "attempt": {"attempt_id": "a1", "status": "SHIPPED", "tracking_number": "FAKE-a1"},
                "outbox": [{"event_type": "OrderAllocated", "attempt_count": 0,
                    "status": "PUBLISHED" if self.relay.started else "PENDING"}]}


class FakeProjection:
    def __init__(self, relay):
        self.relay = relay

    def item(self, ids):
        if not self.relay.started:
            return None
        return {"status": "SHIPPED", "stage": 4, "tracking_number": "FAKE-a1", "package_count": 1}


class FakeRelay:
    started = 0

    def start(self):
        self.started += 1


class FakeCache:
    def __init__(self):
        self.hit_counter = 10
        self.present = False

    def entry(self, ids):
        return {"exists": self.present, "ttl": 29 if self.present else None}

    def hits(self):
        self.hit_counter += 1  # every call after a read is one more hit; the phase reads twice
        return self.hit_counter


class FakeBroker:
    def queue_stats(self, ids):
        return {"processed": 1, "ready": 0, "consumers": 1}


class FakeLogs:
    def find_error(self, request_id):
        return {"stream": {"service": "backend", "level": "ERROR"},
                "line": {"request_id": request_id, "message": "unhandled error"}}


class FakeErrorApi:
    def trigger(self, ids):
        return 200, ids.error_request_id, "INTERNAL: Internal server error"


def build(wait_result=True):
    relay = FakeRelay()
    api = FakeApi()
    ports = Ports(api=api, truth=FakeTruth(relay), projection=FakeProjection(relay), cache=FakeCache(),
                  broker=FakeBroker(), relay=relay, logs=FakeLogs(), error_api=FakeErrorApi(),
                  wait=lambda predicate, timeout: wait_result and predicate())
    return DemoContext(IDS, ports), api, relay


def test_phases_run_in_the_order_the_lifecycle_requires():
    assert [phase.key for phase in build_phases()] == [
        "seed", "create", "allocate", "relay", "cache", "start-picking", "pick", "pack", "ship", "logs"]


def test_the_api_is_driven_through_the_whole_lifecycle_in_order():
    context, api, _ = build()

    run_phases(build_phases(), context, pause=lambda: None, out=lambda text: None)

    mutations = [name for name, _ in api.calls if name != "order"]
    assert mutations == list(MUTATIONS)


def test_the_learner_sees_the_question_and_pauses_before_anything_runs_and_the_answer_comes_last():
    context, api, _ = build()
    events = []
    phase = build_phases()[2]  # allocate

    def pause():
        events.append(("pause", len(api.calls), "\n".join(shown)))

    shown = []
    run_phases([phase], context, pause=pause, out=shown.append)

    (_, calls_at_pause, text_at_pause), = events
    assert calls_at_pause == 0
    assert phase.question in text_at_pause
    assert phase.why not in text_at_pause
    assert phase.why in "\n".join(shown)


def test_allocation_shows_a_pending_outbox_row_before_the_relay_exists():
    context, _, relay = build()
    shown = []

    run_phases(build_phases()[:3], context, pause=lambda: None, out=shown.append)

    assert relay.started == 0
    assert "PENDING" in "\n".join(shown)


def test_the_relay_starts_exactly_once_and_the_projection_is_shown_afterwards():
    context, _, relay = build()
    shown = []

    run_phases(build_phases(), context, pause=lambda: None, out=shown.append)

    assert relay.started == 1
    assert "FAKE-a1" in "\n".join(shown)


def test_a_projection_that_never_catches_up_fails_the_demo_loudly():
    context, _, _ = build(wait_result=False)

    with pytest.raises(DemoFailure, match="relay did not publish"):
        run_phases(build_phases(), context, pause=lambda: None, out=lambda text: None)


def test_the_cache_phase_reports_a_hit_on_the_second_read():
    context, api, _ = build()
    shown = []
    cache_phase = next(phase for phase in build_phases() if phase.key == "cache")

    run_phases([cache_phase], context, pause=lambda: None, out=shown.append)

    assert [name for name, _ in api.calls] == ["order", "order"]
    assert "+1" in "\n".join(shown)


def test_the_log_phase_shows_the_request_id_that_was_sent():
    context, _, _ = build()
    shown = []
    logs_phase = next(phase for phase in build_phases() if phase.key == "logs")

    run_phases([logs_phase], context, pause=lambda: None, out=shown.append)

    assert IDS.error_request_id in "\n".join(shown)
    assert "Internal server error" in "\n".join(shown)


def test_a_missing_log_line_fails_the_demo():
    context, _, _ = build()
    context.ports.logs.find_error = lambda request_id: None
    logs_phase = next(phase for phase in build_phases() if phase.key == "logs")

    with pytest.raises(DemoFailure, match="Loki"):
        run_phases([logs_phase], context, pause=lambda: None, out=lambda text: None)
