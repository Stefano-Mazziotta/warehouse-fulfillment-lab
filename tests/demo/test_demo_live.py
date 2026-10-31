"""Runs the real demo against the live lab stack (see docs/demo.md for the services it needs)."""
import os
import re
import subprocess
from pathlib import Path

import boto3
import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "scripts" / "demo" / "run_demo.sh"

pytestmark = pytest.mark.skipif(
    os.environ.get("LAB_TEST_DEMO") != "1", reason="set LAB_TEST_DEMO=1 to run the demo against the lab stack")


def run_demo(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(ENTRYPOINT), *args], cwd=ROOT, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=240)


def projection_item(client_id: str, order_id: str):
    table = boto3.resource(
        "dynamodb", endpoint_url=os.environ.get("LAB_DYNAMODB_URL", "http://127.0.0.1:58000"),
        region_name="us-east-1", aws_access_key_id="local", aws_secret_access_key="local",
    ).Table("lab_order_projection")
    return table.get_item(Key={"pk": f"OWNER#{client_id}", "sk": f"ORDER#{order_id}"}, ConsistentRead=True).get("Item")


def test_the_demo_runs_unattended_and_the_projection_ends_shipped():
    result = run_demo("--no-pause", "--keep-data")
    run_id = re.search(r"demo run id: (\w+)", result.stdout).group(1)
    try:
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        item = projection_item(f"demo-{run_id}", f"order-{run_id}")
        assert item is not None
        assert item["status"] == "SHIPPED" and int(item["stage"]) == 4
        assert item["tracking_number"].startswith("FAKE-")
        assert "Phase 10/10" in result.stdout
    finally:
        cleaned = run_demo("--cleanup", run_id)
        assert cleaned.returncode == 0, cleaned.stderr
    assert projection_item(f"demo-{run_id}", f"order-{run_id}") is None

