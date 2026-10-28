"""Every request carries one id: accepted from the caller when safe, generated otherwise, always echoed."""
import dataclasses
import logging

import pytest
from sqlalchemy import create_engine

from api.api_services import ApiServices
from api.app_config import AppConfig
from api.app_factory import create_app
from api.request_id_middleware import RequestIdMiddleware
from log_capture_support import capture_logs


class Exploding:
    def execute(self, *_):
        raise RuntimeError("password=hunter2 host=db.internal")


def build_client():
    # No database: /health answers against in-memory SQLite and the one GraphQL query below
    # reaches a service that always fails.
    services = ApiServices(**{field.name: None for field in dataclasses.fields(ApiServices)}
                           | {"get_order_summary": Exploding()})
    app = create_app(AppConfig(database_url="sqlite://"), engine=create_engine("sqlite://"), services=services)
    return app.test_client()


FAILING_QUERY = {"query": '{ order(orderId: "o1") { orderId } }'}


def test_a_caller_supplied_request_id_is_echoed():
    response = build_client().get("/health", headers={"X-Request-Id": "req-123"})
    assert response.headers["X-Request-Id"] == "req-123"


def test_a_missing_request_id_is_generated_and_differs_per_request():
    client = build_client()
    first = client.get("/health").headers["X-Request-Id"]
    assert first and first != client.get("/health").headers["X-Request-Id"]


@pytest.mark.parametrize("hostile", ["x" * 65, "a b", "line\nbreak", "{\"a\":1}", "ünï", ""])
def test_an_unsafe_request_id_is_replaced(hostile):
    # Ids end up in log lines: bounded size and a plain alphabet keep them from forging log content.
    # Called as raw WSGI because the test client refuses to send a newline in a header.
    seen = {}

    def app(environ, start_response):
        start_response("200 OK", [])
        return [b""]

    def start_response(status, headers, exc_info=None):
        seen.update(headers)

    RequestIdMiddleware(app)({"HTTP_X_REQUEST_ID": hostile}, start_response)
    assert seen["X-Request-Id"] != hostile and len(seen["X-Request-Id"]) == 32


def test_the_request_id_is_on_the_error_log_line_of_a_failing_graphql_request():
    client = build_client()
    with capture_logs() as logs:
        response = client.post("/graphql", json=FAILING_QUERY, headers={
            "X-Client-Id": "owner", "X-Request-Id": "req-777"})
    assert response.headers["X-Request-Id"] == "req-777"
    errors = [line for line in logs.lines if line["level"] == "ERROR"]
    assert errors and all(line["request_id"] == "req-777" for line in errors)


def test_the_request_id_does_not_leak_into_logs_written_after_the_request():
    client = build_client()
    client.get("/health", headers={"X-Request-Id": "req-1"})
    with capture_logs() as logs:
        logging.getLogger("lab.after").info("later")
    assert "request_id" not in logs.lines[0]
