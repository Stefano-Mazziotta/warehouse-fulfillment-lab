"""Runs each real drill unattended against the lab stack and re-checks its invariant independently.

Needs LAB_TEST_DRILLS=1 and the services named in docs/failure-drills.md. Drill 7 stops and
restarts the lab's Valkey container.
"""
import os
import re
import subprocess
from pathlib import Path

import boto3
import pytest
import valkey
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "scripts" / "drills" / "run_drill.sh"

pytestmark = pytest.mark.skipif(
    os.environ.get("LAB_TEST_DRILLS") != "1", reason="set LAB_TEST_DRILLS=1 to run the drills against the lab stack")

URLS = {
    "LAB_DATABASE_URL": os.environ.get("LAB_TEST_DATABASE_URL", "postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab"),
    "LAB_AMQP_URL": os.environ.get("LAB_TEST_AMQP_URL", "amqp://lab:lab@127.0.0.1:55672/"),
    "LAB_VALKEY_URL": os.environ.get("LAB_TEST_VALKEY_URL", "valkey://127.0.0.1:56379/0"),
    "LAB_DYNAMODB_URL": os.environ.get("LAB_TEST_DYNAMODB_URL", "http://127.0.0.1:58000"),
}


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(ENTRYPOINT), *args], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=300, env={**os.environ, **URLS})


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(URLS["LAB_DATABASE_URL"])
    yield engine
    engine.dispose()


class Drill:
    """One kept run: its output, its ids, and the guarantee that its rows are removed afterwards."""

    def __init__(self, engine, number: int) -> None:
        self.engine = engine
        self.result = run(str(number), "--no-pause", "--keep-data")
        match = re.search(r"drill run id: (\w+)", self.result.stdout)
        assert match, self.result.stdout[-1500:] + self.result.stderr[-1500:]
        self.run_id = match.group(1)
        self.client = f"D{self.run_id}"

    def scalar(self, sql: str, **params):
        with self.engine.connect() as connection:
            return connection.execute(text(sql), {"c": self.client, **params}).scalar_one()

    def assert_held(self) -> None:
        output = self.result.stdout
        assert self.result.returncode == 0, output[-2500:] + self.result.stderr[-1500:]
        assert "[ok]" in output and "[FAIL]" not in output, output[-2500:]
        assert "1/1 drills held their invariant" in output

    def leftovers(self) -> int:
        tables = ("orders", "inventory_balances", "outbox_messages", "integration_events",
                  "channel_order_versions", "integration_checkpoints", "fake_channel_orders", "fake_carrier_shipments")
        return sum(self.scalar(f"SELECT count(*) FROM {table} WHERE client_id = :c") for table in tables) + self.scalar(
            "SELECT count(*) FROM inbox_messages WHERE consumer_name = :n OR message_id LIKE :p",
            n=f"drill-{self.run_id}", p=f"{self.client}:%")


@pytest.fixture
def drill(engine, request):
    started = Drill(engine, request.param)
    try:
        yield started
    finally:
        cleaned = run("--cleanup", started.run_id)
        assert cleaned.returncode == 0, cleaned.stderr
    assert started.leftovers() == 0


def drilled(number: int):
    return pytest.mark.parametrize("drill", [number], indirect=True, ids=[f"drill-{number}"])


@drilled(1)
def test_two_workers_allocate_the_last_unit_and_exactly_one_wins(drill):
    drill.assert_held()
    assert drill.scalar("SELECT on_hand FROM inventory_balances WHERE client_id = :c") == 1
    assert drill.scalar("SELECT allocated FROM inventory_balances WHERE client_id = :c") == 1
    assert drill.scalar("SELECT count(*) FROM orders WHERE client_id = :c AND status = 'ALLOCATED'") == 1
    assert drill.scalar("SELECT count(*) FROM order_reservations WHERE client_id = :c") == 1
    assert "waiting on worker A's row lock" in drill.result.stdout


@drilled(2)
def test_a_lost_carrier_response_ships_once_and_decrements_stock_once(drill):
    drill.assert_held()
    assert drill.scalar("SELECT status FROM shipping_attempts WHERE client_id = :c") == "SHIPPED"
    assert drill.scalar("SELECT count(*) FROM fake_carrier_shipments WHERE client_id = :c") == 1
    assert drill.scalar("SELECT on_hand FROM inventory_balances WHERE client_id = :c") == 0
    assert drill.scalar("SELECT count(*) FROM outbox_messages WHERE client_id = :c AND event_type = 'OrderShipped'") == 1


@drilled(3)
def test_a_duplicate_webhook_has_one_effect(drill):
    drill.assert_held()
    assert drill.scalar("SELECT count(*) FROM orders WHERE client_id = :c") == 2
    assert drill.scalar("SELECT count(*) FROM integration_events WHERE client_id = :c") == 2
    assert drill.scalar(
        "SELECT count(*) FROM inbox_messages WHERE consumer_name = 'channel-order-ingest' "
        "AND message_id IN (SELECT id FROM integration_events WHERE client_id = :c)") == 2


@drilled(4)
def test_out_of_order_events_leave_the_projection_at_the_maximum_stage(drill):
    drill.assert_held()
    item = boto3.resource(
        "dynamodb", endpoint_url=URLS["LAB_DYNAMODB_URL"], region_name="us-east-1",
        aws_access_key_id="local", aws_secret_access_key="local",
    ).Table("lab_order_projection").get_item(
        Key={"pk": f"OWNER#{drill.client}", "sk": f"ORDER#ORD-{drill.run_id}"}, ConsistentRead=True)["Item"]
    assert (item["status"], int(item["stage"])) == ("SHIPPED", 4)
    assert item["warehouse_id"] == "WH-DEMO"


@drilled(5)
def test_crashes_leave_exactly_one_effect_per_event(drill):
    drill.assert_held()
    assert drill.scalar("SELECT on_hand FROM inventory_balances WHERE client_id = :c") == 4
    assert drill.scalar("SELECT count(*) FROM inbox_messages WHERE consumer_name = :n", n=f"drill-{drill.run_id}") == 4
    assert drill.scalar("SELECT count(*) FROM outbox_messages WHERE client_id = :c AND status = 'PUBLISHED'") == 4
    assert drill.scalar("SELECT count(*) FROM outbox_messages WHERE client_id = :c AND status <> 'PUBLISHED'") == 0
    assert "child exit code -9" in drill.result.stdout


@drilled(6)
def test_a_lost_event_is_repaired_and_the_warehouse_converges(drill):
    drill.assert_held()
    assert drill.scalar("SELECT count(*) FROM orders WHERE client_id = :c") == 4
    assert drill.scalar("SELECT count(*) FROM fake_channel_orders WHERE client_id = :c") == 4
    assert drill.scalar("SELECT cursor FROM integration_checkpoints WHERE client_id = :c") is not None


@drilled(7)
def test_reads_and_allocation_survive_a_valkey_outage_and_valkey_comes_back(drill):
    drill.assert_held()
    assert "[ok] all 10 reads succeeded from PostgreSQL" in drill.result.stdout
    assert drill.scalar("SELECT allocated FROM inventory_balances WHERE client_id = :c") == 2
    assert valkey.Valkey.from_url(URLS["LAB_VALKEY_URL"], socket_timeout=2).ping() is True


@drilled(8)
def test_a_duplicate_edi_document_creates_one_order(drill):
    drill.assert_held()
    assert drill.scalar("SELECT count(*) FROM orders WHERE client_id = :c") == 1
    assert drill.scalar("SELECT quantity FROM order_lines WHERE client_id = :c AND line_id = '1'") == 2
    assert drill.scalar(
        "SELECT count(*) FROM inbox_messages WHERE consumer_name = 'edi-order-intake' AND message_id LIKE :p",
        p=f"{drill.client}:%") == 2


def test_a_bad_selector_is_refused_without_touching_anything():
    result = run("9")
    assert result.returncode == 2 and "1-8" in result.stderr
