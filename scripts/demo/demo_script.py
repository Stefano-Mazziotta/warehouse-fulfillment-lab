"""The demo as data: ten phases, each a prediction question, an action, the evidence and the reason."""
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from demo_format import heading, shorten
from demo_ids import RunIds
from demo_ports import Ports
from demo_state import broker_view, cache_view, postgres_view, projection_view

ON_HAND = 10
QUANTITY = 3
PROJECTION_TIMEOUT_SECONDS = 20.0
LOG_TIMEOUT_SECONDS = 30.0


class DemoFailure(Exception):
    pass


@dataclass(frozen=True)
class DemoContext:
    ids: RunIds
    ports: Ports


@dataclass(frozen=True)
class Phase:
    key: str
    title: str
    question: str
    why: str
    act: Callable[[DemoContext], str]


def run_phases(
    phases: Sequence[Phase], context: DemoContext, *, pause: Callable[[], None], out: Callable[[str], None]
) -> None:
    for number, phase in enumerate(phases, 1):
        out(heading(f"Phase {number}/{len(phases)}: {phase.title}"))
        out(f"PREDICT {phase.question}")
        pause()
        out(phase.act(context))
        out(f"WHY     {phase.why}")


def _transition(context: DemoContext, mutation: str) -> None:
    query = f"mutation($id: String!) {{ {mutation}(orderId: $id) {{ order {{ status }} }} }}"
    context.ports.api.graphql(query, {"id": context.ids.order_id})


def _stock_input(ids: RunIds) -> dict:
    return {"sku": ids.sku, "warehouseId": ids.warehouse_id, "locationId": ids.location_id}


def _await_stage(context: DemoContext, stage: int) -> dict:
    ports, ids = context.ports, context.ids
    reached = lambda: (item := ports.projection.item(ids)) is not None and item["stage"] >= stage  # noqa: E731
    if not ports.wait(reached, PROJECTION_TIMEOUT_SECONDS):
        raise DemoFailure(
            f"the projection did not reach stage {stage} in {PROJECTION_TIMEOUT_SECONDS:.0f}s; "
            "is the projection consumer running (see logs/backend.log)?")
    return ports.projection.item(ids)


def _seed(context: DemoContext) -> str:
    context.ports.truth.seed_stock(context.ids, ON_HAND)
    snapshot = context.ports.truth.snapshot(context.ids)
    return ("ACTION  INSERT one inventory_balances row (there is no API to receive stock)\n"
            + postgres_view(snapshot, ("stock",)))


def _create(context: DemoContext) -> str:
    ids = context.ids
    context.ports.api.graphql(
        "mutation($input: CreateOrderInput!) { createOrder(input: $input) { order { orderId status } } }",
        {"input": {"orderId": ids.order_id, "warehouseId": ids.warehouse_id, "lines": [
            {"lineId": ids.line_id, "sku": ids.sku, "quantity": QUANTITY}]}})
    snapshot = context.ports.truth.snapshot(ids)
    return (f"ACTION  GraphQL createOrder ({QUANTITY} x {ids.sku})\n"
            + postgres_view(snapshot, ("order", "stock", "outbox")))


def _allocate(context: DemoContext) -> str:
    _transition(context, "allocateInventory")
    snapshot = context.ports.truth.snapshot(context.ids)
    return ("ACTION  GraphQL allocateInventory\n"
            + postgres_view(snapshot, ("order", "stock", "reservations", "outbox")) + "\n"
            + projection_view(context.ports.projection.item(context.ids)))


def _relay(context: DemoContext) -> str:
    ports, ids = context.ports, context.ids
    ports.relay.start()
    published = lambda: all(  # noqa: E731
        row["status"] == "PUBLISHED" for row in ports.truth.snapshot(ids)["outbox"])
    if not ports.wait(published, PROJECTION_TIMEOUT_SECONDS):
        raise DemoFailure("the relay did not publish the outbox rows; see logs/backend.log")
    item = _await_stage(context, 1)
    return ("ACTION  start the outbox relay (publishes PENDING rows to RabbitMQ)\n"
            + postgres_view(ports.truth.snapshot(ids), ("outbox",)) + "\n"
            + broker_view(ports.broker.queue_stats(ids)) + "\n" + projection_view(item))


def _order_query(context: DemoContext) -> None:
    context.ports.api.graphql(
        "query($id: String!) { order(orderId: $id) { orderId status } }", {"id": context.ids.order_id})


def _cache(context: DemoContext) -> str:
    cache, ids = context.ports.cache, context.ids
    before = cache.entry(ids)
    _order_query(context)
    after_first = cache.entry(ids)
    hits_after_first = cache.hits()
    _order_query(context)
    delta = cache.hits() - hits_after_first
    return ("ACTION  GraphQL order(...) twice\n"
            f"  before any read:    {cache_view(before)}\n"
            f"  after the 1st read: {cache_view(after_first)}\n"
            f"  after the 2nd read: {cache_view(cache.entry(ids), hits_delta=delta)}")


def _start_picking(context: DemoContext) -> str:
    ports, ids = context.ports, context.ids
    _transition(context, "startPicking")
    return ("ACTION  GraphQL startPicking (a write: it must invalidate the cache)\n"
            + cache_view(ports.cache.entry(ids)) + "\n"
            + postgres_view(ports.truth.snapshot(ids), ("order",)) + "\n"
            + projection_view(ports.projection.item(ids)))


def _held(context: DemoContext) -> list[dict]:
    data = context.ports.api.graphql(
        "query($id: String!) { order(orderId: $id) { reservations { lineId sku warehouseId locationId "
        "quantity pickedQuantity } } }", {"id": context.ids.order_id})
    return data["order"]["reservations"]


def _pick(context: DemoContext) -> str:
    ports, ids = context.ports, context.ids
    for item in _held(context):
        ports.api.graphql(
            "mutation($input: RecordPickInput!) { recordPick(input: $input) { reservation { pickedQuantity } } }",
            {"input": {"orderId": ids.order_id, "lineId": item["lineId"],
                       "stock": {"sku": item["sku"], "warehouseId": item["warehouseId"],
                                 "locationId": item["locationId"]},
                       "pickedQuantity": item["quantity"]}})
    _transition(context, "completePicking")
    projected = _await_stage(context, 2)
    return ("ACTION  GraphQL recordPick (cumulative target) then completePicking\n"
            + postgres_view(ports.truth.snapshot(ids), ("order", "stock", "reservations", "outbox")) + "\n"
            + projection_view(projected))


def _pack(context: DemoContext) -> str:
    ports, ids = context.ports, context.ids
    contents = [{"lineId": item["lineId"],
                 "stock": {"sku": item["sku"], "warehouseId": item["warehouseId"],
                           "locationId": item["locationId"]},
                 "quantity": item["quantity"]} for item in _held(context)]
    ports.api.graphql(
        "mutation($input: AddPackageInput!) { addPackage(input: $input) { package { packageId } } }",
        {"input": {"orderId": ids.order_id, "packageId": ids.package_id, "weightGrams": 900,
                   "lengthMm": 300, "widthMm": 200, "heightMm": 100, "contents": contents}})
    _transition(context, "finishPacking")
    projected = _await_stage(context, 3)
    return ("ACTION  GraphQL addPackage then finishPacking\n"
            + postgres_view(ports.truth.snapshot(ids), ("order", "stock", "packages")) + "\n"
            + projection_view(projected))


def _ship(context: DemoContext) -> str:
    ports, ids = context.ports, context.ids
    ports.api.graphql(
        "mutation($id: String!) { shipOrder(orderId: $id) { shipment { status trackingNumber } } }",
        {"id": ids.order_id})
    projected = _await_stage(context, 4)
    return ("ACTION  GraphQL shipOrder (the carrier is the lab's fake)\n"
            + postgres_view(ports.truth.snapshot(ids), ("order", "stock", "attempt", "outbox")) + "\n"
            + broker_view(ports.broker.queue_stats(ids)) + "\n" + projection_view(projected))


def _logs(context: DemoContext) -> str:
    ports, ids = context.ports, context.ids
    status, echoed, client_error = ports.error_api.trigger(ids)
    found = ports.logs.find_error(ids.error_request_id)
    if found is None:
        raise DemoFailure(
            f"no log line for request id {ids.error_request_id} reached Loki in {LOG_TIMEOUT_SECONDS:.0f}s; "
            "is Alloy up and tailing logs/backend.log (http://127.0.0.1:52345)?")
    line = json.dumps(found["line"])
    return (f"ACTION  send a query that fails on the server with X-Request-Id: {ids.error_request_id}\n"
            f"  the client sees: HTTP {status}, {client_error}, X-Request-Id: {echoed}\n"
            f"  Loki labels: {found['stream']}\n"
            f"  Loki line:   {shorten(line, 300)}\n"
            f"  Grafana:     http://127.0.0.1:53000 (lab / lab-grafana) > Explore > Loki: "
            f'{{service="backend"}} |= "{ids.error_request_id}"')


def build_phases() -> list[Phase]:
    return [
        Phase("seed", "Receive stock (SQL only)",
              f"We receive {ON_HAND} units of one SKU into one bin. What will on_hand, allocated and "
              "available be, and which of them is stored in the table?",
              "available is on_hand - allocated, computed on read. Nothing is reserved yet, so all "
              f"{ON_HAND} units are promisable.", _seed),
        Phase("create", "createOrder",
              f"createOrder asks for {QUANTITY} units. Afterwards, what is available? Is anything in the outbox?",
              "Creating an order records intent only: no stock is reserved and no event is published "
              "(CreateOrder writes nothing to the outbox).", _create),
        Phase("allocate", "allocateInventory",
              "After allocateInventory, what is available? Has anything reached RabbitMQ or DynamoDB, and "
              "what is the status of the outbox row?",
              f"The reservation, the stock change and the OrderAllocated outbox row were committed in ONE "
              f"PostgreSQL transaction (available {ON_HAND}->{ON_HAND - QUANTITY}). The row is PENDING: "
              "no relay is running yet, so no broker or DynamoDB write has happened.", _allocate),
        Phase("relay", "Outbox relay -> RabbitMQ -> projection",
              "We start the relay. What will the outbox row's status become, and what will DynamoDB hold "
              "for this order (and what 'stage')?",
              "The relay publishes the row and marks it PUBLISHED (at-least-once: publish first, mark "
              "second). The projection consumer then writes DynamoDB, stage 1 = ALLOCATED. PostgreSQL "
              "stays the truth; DynamoDB is a derived read model.", _relay),
        Phase("cache", "Order summary cache (Valkey)",
              "We read the order summary twice. Which store answers the second read, and how could you tell?",
              "The first read misses, loads from PostgreSQL and fills Valkey with a 30 s TTL; the second "
              "is a cache hit (keyspace_hits rises) and PostgreSQL is not queried.", _cache),
        Phase("start-picking", "startPicking",
              "startPicking changes the order status. What happens to the cached entry, and will DynamoDB "
              "show PICKING?",
              "Every cached transition is wrapped by an invalidating use case, so the entry is deleted "
              "after the commit. DynamoDB still says ALLOCATED: StartPicking publishes no event, a known "
              "gap in the projection.", _start_picking),
        Phase("pick", "recordPick + completePicking",
              "After picking is complete, do on_hand, allocated or picked change?",
              "Picking moves nothing out of the building: only picked grows, to the reserved quantity. "
              "completePicking also writes PickingCompleted to the outbox (projection stage 2).", _pick),
        Phase("pack", "addPackage + finishPacking",
              "What must be true about the packages before finishPacking is allowed, and does stock change?",
              "Packages must exactly cover every picked reservation. Packing is bookkeeping about boxes, "
              "so stock is unchanged; OrderPacked is written to the outbox (stage 3).", _pack),
        Phase("ship", "shipOrder",
              "After shipOrder, what do on_hand, allocated and picked become? What if the carrier had "
              "timed out instead?",
              "Stock leaves the building: on_hand and allocated drop by the shipped quantity and picked "
              "returns to 0. The attempt row is committed BEFORE the carrier is called; a timeout would "
              "leave it UNKNOWN for reconcileShipment, never a second shipment.", _ship),
        Phase("logs", "A server error, found by request id",
              "We trigger a deliberate server-side failure with our own X-Request-Id. What does the client "
              "learn about the cause, and where do you find the details?",
              "The client gets only the generic INTERNAL error. The JSON log line with the exception and "
              "the same request_id went stderr -> logs/backend.log -> Alloy -> Loki -> Grafana.", _logs),
    ]
