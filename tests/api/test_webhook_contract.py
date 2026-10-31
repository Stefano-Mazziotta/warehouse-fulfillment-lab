"""The published webhook contract must match the real parser and route."""
import json
from pathlib import Path

from api_support import build_adapter_lab
from integrations.domain.ingest_outcome import IngestOutcome

DOCS = Path(__file__).resolve().parents[2] / "docs" / "api"


class RecordingReceiver:
    def __init__(self, outcome=IngestOutcome.CREATED):
        self.outcome, self.events = outcome, []

    def execute(self, event):
        self.events.append(event)
        return self.outcome


def test_documented_example_is_accepted_by_the_route():
    example = json.loads((DOCS / "sales-channel-webhook.example.json").read_text())
    receiver = RecordingReceiver()
    response = build_adapter_lab(receive=receiver).client.post("/webhooks/sales-channel", json=example)
    assert response.status_code == 202
    assert response.get_json() == {"eventId": "evt-1001", "outcome": "CREATED"}
    assert receiver.events[0].order.channel_order_id == "SO-1001"


def test_example_in_the_markdown_is_the_example_file():
    document = (DOCS / "sales-channel-webhook.md").read_text()
    fenced = document.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(fenced) == json.loads((DOCS / "sales-channel-webhook.example.json").read_text())


def test_every_ingest_outcome_is_documented():
    document = (DOCS / "sales-channel-webhook.md").read_text()
    assert all(outcome.value in document for outcome in IngestOutcome)


def test_a_conflict_is_still_a_202_as_documented():
    example = json.loads((DOCS / "sales-channel-webhook.example.json").read_text())
    lab = build_adapter_lab(receive=RecordingReceiver(IngestOutcome.CONFLICT))
    response = lab.client.post("/webhooks/sales-channel", json=example)
    assert (response.status_code, response.get_json()["outcome"]) == (202, "CONFLICT")
