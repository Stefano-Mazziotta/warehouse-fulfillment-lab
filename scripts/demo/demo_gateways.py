"""Real adapters for the ports in demo_ports.py. Thin on purpose: logic worth testing is in demo_script."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import boto3
import pika
import valkey
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import Engine, create_engine, text

from demo_format import exception_summary
from demo_ids import RunIds
from demo_processes import Supervisor, free_port, wait_for_health, wait_until
from demo_script import DemoFailure
from demo_settings import Settings

QUEUE = "orders.projection"
CONSUMER = "order-projection"
TABLE = "lab_order_projection"
# Mirrors ValkeyOrderSummaryCache's key layout; the live test would notice if the two drifted.
CACHE_PREFIX = "lab:order-summary:"
ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT / "logs" / "backend.log"
FLASK_APP = "api.app_factory:create_app_from_environment"


def child_env(settings: Settings, **extra: str) -> dict[str, str]:
    return {**os.environ, "PYTHONUNBUFFERED": "1", "LAB_DATABASE_URL": settings.database_url,
            "LAB_AMQP_URL": settings.amqp_url, "LAB_VALKEY_URL": settings.valkey_url,
            "LAB_DYNAMODB_URL": settings.dynamodb_url, **extra}


class HttpApi:
    def __init__(self, base_url: str, client_id: str) -> None:
        self._url = f"{base_url}/graphql"
        self._client_id = client_id

    def graphql(self, query, variables=None, *, request_id=None):
        headers = {"Content-Type": "application/json", "X-Client-Id": self._client_id}
        if request_id:
            headers["X-Request-Id"] = request_id
        request = urllib.request.Request(
            self._url, json.dumps({"query": query, "variables": variables or {}}).encode(), headers)
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.load(response)
        if "errors" in body:
            codes = [error.get("extensions", {}).get("code") for error in body["errors"]]
            raise DemoFailure(f"GraphQL error {codes}: {body['errors'][0]['message']}")
        return body["data"]


class PostgresTruth:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def seed_stock(self, ids: RunIds, on_hand: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO inventory_balances (client_id, sku, warehouse_id, location_id, on_hand, "
                "allocated, picked, packed) VALUES (:c, :sku, :w, :l, :n, 0, 0, 0)"),
                {"c": ids.client_id, "sku": ids.sku, "w": ids.warehouse_id, "l": ids.location_id, "n": on_hand})

    def snapshot(self, ids: RunIds) -> dict:
        params = {"c": ids.client_id, "o": ids.order_id, "sku": ids.sku}
        with self._engine.connect() as connection:
            def rows(sql: str) -> list[dict]:
                return [dict(row) for row in connection.execute(text(sql), params).mappings()]
            first = lambda sql: (found := rows(sql)) and found[0] or None  # noqa: E731
            return {
                "order": first("SELECT status FROM orders WHERE client_id=:c AND order_id=:o"),
                "stock": first("SELECT on_hand, allocated, picked, packed FROM inventory_balances "
                               "WHERE client_id=:c AND sku=:sku"),
                "reservations": rows("SELECT location_id, quantity, picked_quantity FROM order_reservations "
                                     "WHERE client_id=:c AND order_id=:o ORDER BY line_id"),
                "packages": rows("SELECT p.package_id, p.weight_grams, COALESCE(SUM(i.quantity), 0) AS units "
                                 "FROM packages p LEFT JOIN package_items i USING (client_id, order_id, package_id) "
                                 "WHERE p.client_id=:c AND p.order_id=:o GROUP BY p.package_id, p.weight_grams "
                                 "ORDER BY p.package_id"),
                "attempt": first("SELECT status, tracking_number FROM shipping_attempts "
                                 "WHERE client_id=:c AND order_id=:o"),
                "outbox": rows("SELECT event_type, status, attempt_count FROM outbox_messages "
                               "WHERE client_id=:c ORDER BY created_at, message_id"),
            }

    def processed_count(self, ids: RunIds) -> int:
        with self._engine.connect() as connection:
            return connection.execute(text(
                "SELECT count(*) FROM inbox_messages WHERE consumer_name=:n AND message_id IN "
                "(SELECT message_id FROM outbox_messages WHERE client_id=:c)"),
                {"n": CONSUMER, "c": ids.client_id}).scalar_one()

    def schema_is_migrated(self) -> bool:
        with self._engine.connect() as connection:
            return connection.execute(text(
                "SELECT to_regclass('outbox_messages') IS NOT NULL AND to_regclass('shipping_attempts') IS NOT NULL"
            )).scalar_one()

    def delete_run(self, ids: RunIds) -> None:
        # Child tables first; every statement is scoped to this run's client id.
        statements = [
            "DELETE FROM shipping_attempt_packages WHERE client_id=:c",
            "DELETE FROM shipping_attempts WHERE client_id=:c",
            "DELETE FROM fake_carrier_shipments WHERE client_id=:c",
            "DELETE FROM package_items WHERE client_id=:c",
            "DELETE FROM packages WHERE client_id=:c",
            "DELETE FROM order_reservations WHERE client_id=:c",
            "DELETE FROM order_lines WHERE client_id=:c",
            "DELETE FROM orders WHERE client_id=:c",
            "DELETE FROM inventory_balances WHERE client_id=:c",
            f"DELETE FROM inbox_messages WHERE consumer_name='{CONSUMER}' AND message_id IN "
            "(SELECT message_id FROM outbox_messages WHERE client_id=:c)",
            "DELETE FROM outbox_messages WHERE client_id=:c",
        ]
        with self._engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement), {"c": ids.client_id})
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{ids.error_schema}" CASCADE'))


class DynamoProjection:
    def __init__(self, url: str) -> None:
        # DynamoDB Local ignores credentials and region, but botocore insists on both.
        self._table = boto3.resource(
            "dynamodb", endpoint_url=url, region_name="us-east-1",
            aws_access_key_id="local", aws_secret_access_key="local").Table(TABLE)

    @staticmethod
    def _key(ids: RunIds) -> dict:
        return {"pk": f"OWNER#{ids.client_id}", "sk": f"ORDER#{ids.order_id}"}

    def item(self, ids: RunIds) -> dict | None:
        try:
            raw = self._table.get_item(Key=self._key(ids), ConsistentRead=True).get("Item")
        except (ClientError, BotoCoreError):
            return None  # table not created yet: same as "no item"
        if raw is None or "stage" not in raw:
            return None
        return {k: int(v) if isinstance(v, Decimal) else v for k, v in raw.items()}

    def delete(self, ids: RunIds) -> None:
        try:
            self._table.delete_item(Key=self._key(ids))
        except (ClientError, BotoCoreError):
            pass


class ValkeyCache:
    def __init__(self, url: str) -> None:
        self._client = valkey.Valkey.from_url(url, socket_timeout=2)

    @staticmethod
    def _key(ids: RunIds) -> str:
        return f"{CACHE_PREFIX}{quote(ids.client_id, safe='')}:{quote(ids.order_id, safe='')}"

    def entry(self, ids: RunIds) -> dict:
        ttl = self._client.ttl(self._key(ids))
        return {"exists": ttl != -2, "ttl": ttl if ttl >= 0 else None}

    def hits(self) -> int:
        return int(self._client.info("stats")["keyspace_hits"])

    def delete(self, ids: RunIds) -> None:
        self._client.delete(self._key(ids))


class Broker:
    def __init__(self, amqp_url: str, truth: PostgresTruth) -> None:
        self._parameters = pika.URLParameters(amqp_url)
        self._truth = truth

    def _passive_declare(self):
        connection = pika.BlockingConnection(self._parameters)
        try:
            return connection.channel().queue_declare(QUEUE, passive=True).method
        finally:
            connection.close()

    def consumers(self) -> int:
        try:
            return self._passive_declare().consumer_count
        except pika.exceptions.AMQPError:
            return 0  # queue not declared yet

    def queue_stats(self, ids: RunIds) -> dict:
        method = self._passive_declare()
        return {"ready": method.message_count, "consumers": method.consumer_count,
                "processed": self._truth.processed_count(ids)}


class RelayProcess:
    def __init__(self, supervisor: Supervisor, settings: Settings, ids: RunIds) -> None:
        self._supervisor, self._settings, self._ids = supervisor, settings, ids

    def start(self) -> None:
        self._supervisor.start(
            "outbox relay",
            [str(Path(__file__).with_name("outbox_relay_worker.py")), self._ids.client_id],
            child_env(self._settings))


class LokiLogs:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self._url = base_url
        self._timeout = timeout_seconds

    def find_error(self, request_id: str) -> dict | None:
        query = f'{{service="backend", level="ERROR"}} |= "{request_id}"'
        start = f"{int(time.time()) - 300}000000000"
        found: list[dict] = []

        def poll() -> bool:
            url = f"{self._url}/loki/api/v1/query_range?" + urllib.parse.urlencode(
                {"query": query, "start": start, "limit": 5})
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    result = json.load(response)["data"]["result"]
            except (urllib.error.URLError, OSError, ValueError):
                return False
            if result:
                found.append(result[0])
            return bool(result)

        if not wait_until(poll, self._timeout, interval=1.0):
            return None
        stream = found[0]
        line = json.loads(stream["values"][0][1])
        if "exception" in line:
            line["exception"] = exception_summary(line["exception"]) + "  [traceback trimmed]"
        return {"stream": stream["stream"], "line": line}


class ErrorApi:
    """A second API process on an empty schema: every order query hits a missing table.

    The same technique as scripts/smoke_observability.sh. The main API keeps running on the
    real schema, so the failure never touches the demo's data.
    """

    def __init__(self, supervisor: Supervisor, settings: Settings, engine: Engine) -> None:
        self._supervisor, self._settings, self._engine = supervisor, settings, engine

    def trigger(self, ids: RunIds) -> tuple[int, str, str]:
        with self._engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ids.error_schema}"'))
        separator = "&" if "?" in self._settings.database_url else "?"
        url = f"{self._settings.database_url}{separator}options=-csearch_path%3D{ids.error_schema}"
        port = free_port()
        child = self._supervisor.start(
            "error API",
            ["-m", "flask", "--app", FLASK_APP, "run", "--port", str(port)],
            child_env(self._settings, LAB_DATABASE_URL=url))
        try:
            base = f"http://127.0.0.1:{port}"
            wait_for_health(base, child)
            request = urllib.request.Request(
                f"{base}/graphql",
                json.dumps({"query": f'{{ order(orderId: "{ids.order_id}") {{ orderId }} }}'}).encode(),
                {"Content-Type": "application/json", "X-Client-Id": ids.client_id,
                 "X-Request-Id": ids.error_request_id})
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    status, headers, body = response.status, response.headers, json.load(response)
            except urllib.error.HTTPError as error:
                status, headers, body = error.code, error.headers, json.loads(error.read() or b"{}")
            errors = body.get("errors") or [{}]
            shown = f"{errors[0].get('extensions', {}).get('code')}: {errors[0].get('message')}"
            return status, headers.get("X-Request-Id", ""), shown
        finally:
            self._supervisor.stop(child)


def make_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)
