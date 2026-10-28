"""End to end through the real pipeline: formatter -> logs/backend.log -> Alloy -> Loki.

Needs the Compose stack (`up -d --wait loki alloy`); skipped unless LAB_TEST_LOKI_URL is set.
The line is appended to the same file the backend redirects its stderr to, so Alloy
cannot tell it from a real backend line.
"""
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from observability.configure_logging import configure_logging
from observability.log_context import log_context

BACKEND_LOG = Path(__file__).resolve().parents[2] / "logs" / "backend.log"


@pytest.fixture
def loki_url():
    url = os.environ.get("LAB_TEST_LOKI_URL")
    if not url:
        pytest.skip("set LAB_TEST_LOKI_URL for the real Loki pipeline proof")
    return url.rstrip("/")


def query_loki(base_url: str, logql: str) -> list[dict]:
    now = time.time_ns()
    params = urllib.parse.urlencode({
        "query": logql, "start": now - 10 * 60 * 10**9, "end": now + 60 * 10**9, "limit": 10})
    with urllib.request.urlopen(f"{base_url}/loki/api/v1/query_range?{params}", timeout=5) as response:
        return json.load(response)["data"]["result"]


def test_an_error_line_written_to_the_backend_log_reaches_loki(loki_url):
    marker = f"pipeline-proof-{uuid4().hex}"
    BACKEND_LOG.parent.mkdir(exist_ok=True)
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    with BACKEND_LOG.open("a") as backend_log:
        try:
            configure_logging(stream=backend_log, level="INFO")
            with log_context(request_id=marker):
                logging.getLogger("smoke.pipeline").error("pipeline proof")
        finally:
            root.handlers[:], root.level = handlers, level

    deadline = time.monotonic() + 30
    streams = []
    while not streams and time.monotonic() < deadline:
        time.sleep(1)
        streams = query_loki(loki_url, f'{{service="backend"}} |= "{marker}"')
    assert streams, "the line did not reach Loki within 30 s (is Alloy running and mounting ./logs?)"
    labels = streams[0]["stream"]
    assert labels["level"] == "ERROR" and labels["logger"] == "smoke.pipeline"
    # Cardinality guard: per-request ids stay in the content, never in the labels.
    assert "request_id" not in labels
    assert json.loads(streams[0]["values"][0][1])["request_id"] == marker
