import re
from datetime import datetime, timezone

import pytest

from demo_ids import RunIds, new_run_ids

NOW = datetime(2026, 10, 29, 10, 15, 30, tzinfo=timezone.utc)


def test_every_id_is_derived_from_the_run_id():
    ids = new_run_ids(NOW, "ab12")

    assert ids.run_id == "1029101530ab12"
    assert ids.client_id == "demo-1029101530ab12"
    assert ids.order_id == "order-1029101530ab12"
    assert ids.sku == "SKU-1029101530AB12"
    assert ids.error_request_id == "demo-err-1029101530ab12"


def test_two_runs_in_the_same_second_get_different_clients():
    assert new_run_ids(NOW, "aaaa").client_id != new_run_ids(NOW, "bbbb").client_id


def test_cleanup_can_rebuild_the_ids_from_the_run_id_alone():
    original = new_run_ids(NOW, "ab12")

    assert RunIds.from_run_id(original.run_id) == original


@pytest.mark.parametrize("bad", ["", "x", "1029101530ab12; DROP TABLE orders", "../etc", "1029101530AB12"])
def test_a_run_id_that_could_inject_sql_or_paths_is_rejected(bad):
    with pytest.raises(ValueError):
        RunIds.from_run_id(bad)


def test_ids_fit_what_the_api_and_postgres_accept():
    ids = new_run_ids(NOW, "ab12")

    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", ids.error_request_id)
    assert re.fullmatch(r"[a-z0-9_]+", ids.error_schema)
