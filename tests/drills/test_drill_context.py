import re
from datetime import datetime, timezone

import pytest

from demo_settings import Settings
from drill_context import DELETE_STATEMENTS, DrillIds, missing_drill_services, new_drill_ids

NOW = datetime(2026, 10, 29, 10, 15, 30, tzinfo=timezone.utc)


def test_every_id_is_derived_from_the_run_id():
    ids = new_drill_ids(NOW, "ab12")

    assert ids.client_id == "D1029101530ab12"
    assert ids.order_id == "ORD-1029101530ab12"
    assert ids.order("A") == "ORD-A-1029101530ab12"
    assert ids.queue == "drill.1029101530ab12"
    assert ids.consumer_name == "drill-1029101530ab12"
    assert ids.event_type == "DrillStockReceived.1029101530ab12"


def test_the_client_id_fits_an_edi_sender_field():
    # ISA06 is 15 characters wide; drill 8 uses the client id as the EDI sender.
    assert len(new_drill_ids(NOW, "ab12").client_id) == 15


def test_a_drill_run_id_that_could_inject_sql_is_rejected():
    with pytest.raises(ValueError):
        DrillIds.from_run_id("1029101530ab12'; DROP TABLE orders; --")


def test_cleanup_rebuilds_the_same_ids_from_the_run_id_alone():
    assert DrillIds.from_run_id("1029101530ab12") == new_drill_ids(NOW, "ab12")


def test_every_cleanup_statement_is_scoped_to_one_drill_run():
    for statement in DELETE_STATEMENTS:
        assert re.search(r":c\b|:prefix\b|:drill\b", statement), statement
    assert not any(statement.strip().upper().startswith(("TRUNCATE", "DROP")) for statement in DELETE_STATEMENTS)


def test_cleanup_removes_dependents_before_the_orders_they_reference():
    statements = list(DELETE_STATEMENTS)
    versions = next(i for i, s in enumerate(statements) if "channel_order_versions" in s)
    inbox_for_events = next(i for i, s in enumerate(statements) if "integration_events" in s and "inbox" in s)
    events = next(i for i, s in enumerate(statements) if s.startswith("DELETE FROM integration_events"))
    assert inbox_for_events < events and versions >= 0


def test_drills_need_only_the_four_stateful_services():
    settings = Settings.from_environ({})
    asked = []

    def is_open(host, port):
        asked.append(port)
        return port != settings.endpoints()["valkey"][1]

    assert missing_drill_services(settings, is_open) == ["valkey"]
    assert len(asked) == 4


def test_deferred_cleanups_run_newest_first_and_one_failure_does_not_strand_the_rest():
    from drill_context import DrillContext

    ran = []
    context = DrillContext(None, None, None, None, None, print)
    context.defer(lambda: ran.append("first"))
    context.defer(lambda: (_ for _ in ()).throw(RuntimeError("broker gone")))
    context.defer(lambda: ran.append("third"))

    failures = context.close()

    assert ran == ["third", "first"]
    assert [str(f) for f in failures] == ["broker gone"]
    assert context.close() == []
