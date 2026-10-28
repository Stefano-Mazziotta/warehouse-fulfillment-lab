"""An unexpected failure is logged once, with traceback, where errors are mapped; clients still see INTERNAL."""
import dataclasses

from sqlalchemy import create_engine

from api.api_services import ApiServices
from api.app_config import AppConfig
from api.app_factory import create_app
from orders.application.order_not_found import OrderNotFound
from log_capture_support import capture_logs

QUERY = {"query": '{ order(orderId: "o1") { orderId } }'}


class Missing:
    def execute(self, *_):
        raise OrderNotFound("o1")


class Exploding:
    def execute(self, *_):
        raise RuntimeError("password=hunter2 host=db.internal")


def client_with(summary_service):
    services = ApiServices(**{field.name: None for field in dataclasses.fields(ApiServices)}
                           | {"get_order_summary": summary_service})
    app = create_app(AppConfig(database_url="sqlite://"), engine=create_engine("sqlite://"), services=services)
    return app.test_client()


def test_an_unexpected_error_logs_exactly_one_line_with_the_traceback():
    with capture_logs() as logs:
        response = client_with(Exploding()).post("/graphql", json=QUERY, headers={"X-Client-Id": "owner"})
    assert response.get_json()["errors"][0]["extensions"]["code"] == "INTERNAL"
    (line,) = logs.from_logger("api.errors")
    assert line["level"] == "ERROR"
    assert "RuntimeError" in line["exception"] and "Traceback" in line["exception"]
    assert line["graphql_path"] == ["order"]


def test_the_client_response_is_unchanged_and_still_hides_the_detail():
    with capture_logs():
        response = client_with(Exploding()).post("/graphql", json=QUERY, headers={"X-Client-Id": "owner"})
    body = response.get_data(as_text=True)
    assert response.get_json()["errors"][0]["message"] == "Internal server error"
    assert "hunter2" not in body and "Traceback" not in body


def test_expected_domain_failures_are_not_logged_as_errors():
    # NOT_FOUND is a normal outcome, not an incident: it must not page anyone.
    with capture_logs() as logs:
        client_with(Missing()).post("/graphql", json=QUERY, headers={"X-Client-Id": "owner"})
    assert logs.from_logger("api.errors") == []
