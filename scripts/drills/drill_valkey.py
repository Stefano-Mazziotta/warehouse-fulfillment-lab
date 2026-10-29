"""Drill 7: Valkey goes down; the API keeps serving from PostgreSQL."""
import subprocess
import sys
import time

from demo_gateways import FLASK_APP, LOG_PATH, HttpApi, ValkeyCache, child_env
from demo_processes import free_port, port_is_open, wait_for_health, wait_until
from demo_settings import COMPOSE_PROJECT
from demo_script import DemoFailure
from drill_context import DrillContext, ROOT_DIR
from drill_core import Check, Drill, DrillFailure, Explanation, Outcome
from drill_verdicts import count_cache_warnings, warnings_allowed

READS = 10
WARNING_WINDOW_SECONDS = 5.0  # ValkeyOrderSummaryCache.log_interval_seconds
ORDER_QUERY = "query($id: String!) { order(orderId: $id) { orderId status } }"
CREATE = "mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId status } } }"
ALLOCATE = "mutation($id: String!) { allocateInventory(orderId: $id) { order { status } } }"


def compose(*args: str) -> None:
    command = ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", str(ROOT_DIR / "compose.yaml"), *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise DrillFailure(f"`docker compose {' '.join(args)}` failed: {result.stderr.strip()[-300:]}")


def act(context: DrillContext) -> Outcome:
    ids, settings, say, truth = context.ids, context.settings, context.say, context.truth
    host, port = settings.endpoints()["valkey"]
    cache = ValkeyCache(settings.valkey_url)
    truth.seed_stock(ids, 10)
    api_port = free_port()
    base = f"http://127.0.0.1:{api_port}"
    api_process = context.supervisor.start(
        "API", ["-m", "flask", "--app", FLASK_APP, "run", "--port", str(api_port)], child_env(settings))
    try:
        wait_for_health(base, api_process)
    except RuntimeError as error:
        raise DrillFailure(str(error)) from error
    api = HttpApi(base, ids.client_id)
    line = {"lineId": ids.line_id, "sku": ids.sku, "quantity": 1}

    def new_order(order_id: str) -> None:
        api.graphql(CREATE, {"input": {"orderId": order_id, "warehouseId": ids.warehouse_id, "lines": [line]}})
        api.graphql(ALLOCATE, {"id": order_id})

    def read_status() -> str:
        try:
            return api.graphql(ORDER_QUERY, {"id": ids.order_id})["order"]["status"]
        except DemoFailure as failure:
            return f"FAILED: {failure}"

    new_order(ids.order_id)
    read_status()
    warm = cache.entry(ids)
    say(f"Valkey up: one read filled the cache (key exists: {warm['exists']}, ttl {warm['ttl']}s)")

    log_offset = LOG_PATH.stat().st_size
    statuses: list[str] = []
    second_allocated = None
    started = time.monotonic()
    try:
        compose("stop", "valkey")
        said_down = wait_until(lambda: not port_is_open(host, port), 15)
        say(f"docker compose stop valkey -> port {port} closed: {said_down}")
        for _ in range(READS):
            statuses.append(read_status())
        second = ids.order("2")
        new_order(second)
        second_allocated = truth.scalar(
            "SELECT status FROM orders WHERE client_id = :c AND order_id = :o", c=ids.client_id, o=second)
    finally:
        elapsed = time.monotonic() - started
        compose("up", "-d", "--wait", "valkey")
    say(f"{READS} reads while Valkey was down -> {sorted(set(statuses))}; a second order created and allocated "
        f"-> {second_allocated}; the whole burst took {elapsed:.1f}s")
    allocated = truth.scalar("SELECT allocated FROM inventory_balances WHERE client_id = :c", c=ids.client_id)
    with open(LOG_PATH, "rb") as log:
        log.seek(log_offset)
        new_lines = log.read().decode(errors="replace").splitlines()
    warnings = count_cache_warnings(new_lines)
    shown = next((entry for entry in new_lines if "cache unavailable" in entry), "(none)")
    say(f"warnings in logs/backend.log during the outage: {warnings} (allowed for {elapsed:.1f}s: 1..{1 + int(elapsed // WARNING_WINDOW_SECONDS)})")
    say(f"  {shown[:230]}")

    def refilled() -> bool:
        read_status()
        return cache.entry(ids)["exists"]

    healthy = port_is_open(host, port) and wait_until(refilled, 20, interval=1.0)
    say(f"Valkey restarted: healthy and refilled by a read after the API's cooldown: {healthy}")
    return Outcome((
        Check("Valkey was really down (docker compose stop; its port closed)", said_down),
        Check(f"all {READS} reads succeeded from PostgreSQL with the right status", statuses == ["ALLOCATED"] * READS),
        Check("allocating a second order worked during the outage and reserved stock (allocated = 2)",
              second_allocated == "ALLOCATED" and allocated == 2),
        Check("the cache failure was reported as throttled warning(s), not one line per call",
              warnings_allowed(warnings, elapsed, window_seconds=WARNING_WINDOW_SECONDS)),
        Check("Valkey came back healthy and the next reads refilled the cache", healthy),
    ))


DRILL = Drill(
    7, "valkey-down", "Valkey is down",
    "The order-summary cache (Valkey) is stopped for real while the API is serving traffic. "
    "Ten reads and a brand-new order allocation hit the API during the outage.",
    "Do the reads fail, slow down, or return stale data? Does allocating stock ever look at the cache? "
    "How many log lines will the outage produce for those eleven operations, and where do you find them?",
    Explanation(
        invariant="the cache is an optimization: its failure never changes an answer or blocks a write",
        mechanism="CachingOrderQueries treats any cache error as a miss and skips the cache for a 5 s "
                  "cooldown (one short timeout per window, not per request); allocation reads and locks "
                  "PostgreSQL only; invalidation after a commit is best effort; the Valkey adapter logs one "
                  "throttled warning per window instead of a stack trace per call",
        without="a cache exception becomes a 500 on reads (or worse, a failed write after commit); an "
                "unthrottled warning floods the log and hides the real errors during exactly the incident "
                "you need to read it",
        trade_off="reads are slower (PostgreSQL does all the work) and a lost invalidation can serve a stale "
                  "summary for up to the 30 s TTL; Valkey is not durable, so nothing may live ONLY there"),
    act)
