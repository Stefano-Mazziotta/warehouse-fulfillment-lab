# Warehouse fulfillment lab

A domain-first Python learning lab. The first inventory slice uses a `src/`
layout. Domain and application stay independent of Flask, databases, and queues;
PostgreSQL infrastructure supplies atomic single-balance allocation.

## Run locally

With Python 3.11+ and [uv](https://docs.astral.sh/uv/) installed:

```sh
uv sync
uv run pytest
```

## Follow one inventory read

```text
src/inventory/
    domain/         # Stock identity, immutable balances, inventory rules
    application/    # GetInventory and its read repository Protocol
    infrastructure/ # InMemoryInventoryRepository
tests/inventory/    # Domain, application, infrastructure, and import-boundary tests
```

The domain separates stock identity (`domain/inventory_key.py`), rule violations
(`domain/inventory_error.py`), and balance behavior
(`domain/inventory_balance.py`). Balance rules stay together: quantities are
nonnegative integers, allocated cannot exceed
on hand, and picked cannot exceed allocated. Available is on hand minus
allocated. Receiving increases on hand without changing reservations.

Module names follow their class names in snake_case: `InventoryBalance` lives
in `inventory_balance.py`. Start with the class that names the business concept
you want to understand.

The application orchestrates a read through `GetInventory`
(`application/get_inventory.py`). It owns the
`InventoryRepository` port (`application/inventory_repository.py`) and the
`InventoryNotFound` error (`application/inventory_not_found.py`): absence is a
use-case outcome, not an invalid stock state. Infrastructure supplies the
in-memory adapter, which satisfies the port structurally without inheriting
from its Protocol. Domain imports no other layer; application imports domain;
infrastructure may depend on the inner layers.

```python
from inventory.infrastructure.in_memory_inventory_repository import (
    InMemoryInventoryRepository,
)
from inventory.application.get_inventory import GetInventory
from inventory.domain import InventoryBalance, InventoryKey

key = InventoryKey("client-a", "SKU-123", "warehouse-1", "04-B-12")
repository = InMemoryInventoryRepository([InventoryBalance(key, on_hand=5)])
get_inventory = GetInventory(repository)
assert get_inventory.execute(key).available == 5
```

A missing identity raises the application-level `InventoryNotFound` error.
Client means inventory owner, not buyer. Client, SKU, warehouse, and location
jointly identify a balance in this provisional lab model.

## Add Flask later, outside the core

A future Flask adapter can translate HTTP parameters into `InventoryKey`, call
the injected `get_inventory.execute(key)`, serialize the result, and translate
`InventoryNotFound` to HTTP 404. Wire the repository and use case at startup
as above, not inside the domain. The GraphQL API section below does exactly this.

## Run transactional allocation with PostgreSQL

The cached `postgres:16-alpine` image is required; Compose never pulls it.
The lab owns only Compose project `warehouse-fulfillment-lab`, loopback port
55432, and its named data volume. Credentials below are local lab values only.

```sh
docker compose -p warehouse-fulfillment-lab up -d --wait postgres
export LAB_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
uv run alembic upgrade head
LAB_TEST_DATABASE_URL="$LAB_DATABASE_URL" uv run pytest
```

Without `LAB_TEST_DATABASE_URL`, PostgreSQL tests explicitly skip. A green
unit-only run is NOT proof of database concurrency safety. Integration tests
create and drop only randomly named `lab_test_<uuid>` schemas in the supplied
PostgreSQL database; point them only at a disposable local lab database.

`AllocateInventory.execute(key, quantity)` locks one complete stock identity,
applies the domain rule, and commits its new balance. Use a fresh
`PostgresInventoryTransaction` per call; `PostgresInventoryRepository` remains
read-only. See [the transaction walkthrough](docs/study/transactional-allocation.md).
There is no HTTP server yet.

```python
from sqlalchemy import create_engine
from inventory.application.allocate_inventory import AllocateInventory
from inventory.infrastructure.postgres_inventory_transaction import (
    PostgresInventoryTransaction,
)

engine = create_engine("postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab")
allocate = AllocateInventory(lambda: PostgresInventoryTransaction(engine))
# With a balance already present: allocate.execute(key, 1)
engine.dispose()
```

## Run the RabbitMQ transport

Compose also defines `rabbitmq` (`rabbitmq:3-management-alpine`, pulled from Docker Hub
on first use) on loopback AMQP port 55672 and management UI port 55673, with the
`rabbitmq-data` volume. Credentials are local lab values only.

```sh
docker compose -p warehouse-fulfillment-lab up -d --wait postgres rabbitmq
export LAB_TEST_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
export LAB_TEST_AMQP_URL=amqp://lab:lab@127.0.0.1:55672/
uv run pytest
```

Without `LAB_TEST_AMQP_URL` the broker tests explicitly skip. They use uniquely named
exchanges and queues and delete them afterwards. See
[the messaging study note](docs/study/messaging.md#rabbitmq-transport).

Stop only the lab with `docker compose -p warehouse-fulfillment-lab down`.
This preserves its data volume. `uv run alembic downgrade base` removes the lab
inventory table and all its balances: use only against this disposable database.

## Order-owned allocation and cancellation

Orders now own reservations across multiple balances in one warehouse. Create,
read, allocate and cancel through application use cases; no HTTP endpoint exists
in this slice. New orders must be CREATED. Inventory is still seeded explicitly.

```python
from orders.application.create_order import CreateOrder
from orders.application.get_order import GetOrder
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder
from orders.domain import Order, OrderKey, OrderLine
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction

transaction = lambda: PostgresOrderTransaction(engine)
order_key = OrderKey("client-a", "order-1")
create = CreateOrder(transaction)
create.execute(Order(order_key, "warehouse-1", (OrderLine("1", "SKU-123", 2),)))
# With two available units seeded for this owner/warehouse:
# AllocateOrder(transaction).execute(order_key)
# CancelOrder(transaction).execute(order_key)
assert GetOrder(transaction).execute(order_key).key == order_key
```

Use a live `engine` as in the PostgreSQL setup above (before `engine.dispose()`).
Run `uv run alembic upgrade head` to install the order migration. The application
locks order then candidate stock in sorted SKU/location order; reservation rows,
stock and state commit together. Identical create retries return the existing
order; conflicting payloads fail. Repeated allocation/cancellation are no-ops.
Cancellation retains historical reservation rows, inactive through CANCELLED
order state, and releases only this order's stock.

Read [the allocation walkthrough](docs/study/order-allocation.md) and
[the transaction decision](docs/decisions/order-transaction.md). Migration rollback
`uv run alembic downgrade 0001_inventory` removes orders, lines and reservations;
it does not undo allocations in inventory. Use it only in disposable schemas,
or reconcile reservations/stock before any destructive operational downgrade.

The earlier single-balance `AllocateInventory` remains a low-level,
non-idempotent exercise, not the order allocation path. Order-owned partial picking now enforces its cancellation cutoff;
order-owned packages now reconcile picked quantities; shipping is described below.

## Order-owned partial picking

Run migration `0003_picking` with `uv run alembic upgrade head`. Start picking,
record cumulative picked targets per complete reservation identity, then complete
only when every order line is fully picked. Picking changes neither on hand nor
allocated stock. Cancellation is rejected once picking starts.

`StartPicking`, `RecordPick` and `CompletePicking` live in
`src/picking/application/` and share the order transaction factory above.
See [the picking walkthrough](docs/study/picking.md) for retry semantics,
concurrency proofs, scanner tradeoffs and the guarded downgrade.


## Order-owned packages and packing completion

Migration `0004_packing` adds immutable packages with positive integer gram/mm
measurements and contents attributed to complete owned reservation identities.
`AddPackage` accepts new packages only for `PICKED` orders; identical canonical
retries are safe even after completion. `FinishPacking` requires exact package,
reservation and line totals before moving the order to `PACKED`.

Both use cases live in `src/packing/application/` and share the order transaction
factory. Packing locks the order, not inventory, and does not change balance-wide
counters. Packages cannot be edited or removed in this slice. Read
[the packing walkthrough](docs/study/packing.md) for conservation rules,
concurrency proofs and the guarded downgrade to `0003_picking`.

## Shipping with an unreliable carrier

Migration `0005_shipping` adds one persisted shipping attempt per order.
`ShipOrder` commits the attempt before calling the `CarrierPort`, never holds a
database transaction across the call, and treats timeouts as `UNKNOWN`.
`ReconcileShipment` looks the attempt up first and retries creation with the
same attempt ID only on an authoritative NOT_FOUND. Finalization decrements
on-hand, allocated and picked stock once and moves the order to `SHIPPED`.
The fake carrier (`PostgresFakeCarrier`) is the only adapter; no network or real
carrier is involved. See [the shipping walkthrough](docs/study/shipping.md).

## Reliable events with an outbox

Migration `0006_messaging` adds `outbox_messages` and `inbox_messages`. Order
allocation and cancellation, picking completion, packing completion and shipment
write their event in the same PostgreSQL transaction as the state change. An
`OutboxRelay` claims due rows with `FOR UPDATE SKIP LOCKED`, publishes through a
`MessagePublisher` port, retries with bounded exponential backoff and marks rows
`DEAD` after the limit. `IdempotentConsumer` records the inbox row and the handler's
effects together, so redelivery is harmless. Delivery is at-least-once and ordering is
not guaranteed. There is no broker adapter yet; `InMemoryPublisher` is the only
publisher. See [the messaging walkthrough](docs/study/messaging.md).

## Repairing lost events with reconciliation

Migration `0007_integrations` adds `integration_events` (raw events, persisted before
processing), `integration_checkpoints` (per source and owner) and
`channel_order_versions` (the accepted channel version per order). A fake sales channel
is the source of truth; `ReceiveChannelEvent` feeds webhook-style events and
`ReconcileChannelOrders` feeds polled pages through the same idempotent ingest path. The
checkpoint advances only after a page is durably processed, the first page re-reads an
overlap window, and a row lock serializes concurrent reconcilers. No HTTP or broker is
wired yet. See [the reconciliation walkthrough](docs/study/reconciliation.md).

## GraphQL API (Flask host)

`src/api/` is the composition root and a thin adapter: `create_app(config)` builds the
engine, transaction factories and use cases, then hosts GraphQL at `POST /graphql` plus two
REST routes, `GET /health` and `POST /webhooks/sales-channel`. Domain and application code
never import Flask or Strawberry (architecture tests enforce it).

```sh
docker compose -p warehouse-fulfillment-lab up -d --wait postgres
export LAB_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
uv run alembic upgrade head
uv run flask --app 'api.app_factory:create_app_from_environment' run --port 5000
```

```sh
curl -s localhost:5000/health
curl -s localhost:5000/graphql -H 'Content-Type: application/json' -H 'X-Client-Id: client-a' \
  -d '{"query":"{ orders(first: 5) { nodes { orderId status lines { sku quantity } } pageInfo { hasNextPage endCursor } } }"}'
```

Every GraphQL request needs `X-Client-Id`; it scopes everything to that owner and is only a
stand-in for authentication. Inventory is still seeded directly in SQL. The committed
contract is `docs/api/schema.graphql`; regenerate it after an intentional change with
`uv run python scripts/export_graphql_schema.py`. See
[the API study note](docs/study/graphql-api.md).

## Logs in Grafana (Loki and Alloy)

The backend runs on the host and writes one JSON object per line to **stderr**; it knows
nothing about Loki. The shell redirects stderr to `logs/backend.log`, Grafana Alloy tails
that file through a bind mount and pushes to Loki, and Grafana reads Loki.

```sh
docker compose -p warehouse-fulfillment-lab up -d --wait loki alloy grafana   # logs/ ships in the repo
export LAB_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
uv run flask --app 'api.app_factory:create_app_from_environment' run --port 5000 2>> logs/backend.log
# in other terminals (LAB_AMQP_URL and LAB_DYNAMODB_URL as in the projection note):
uv run python -m orders.infrastructure.order_projection_cli run 2>> logs/backend.log
```

- Grafana: <http://127.0.0.1:53000> (user `lab`, password `lab-grafana`, lab only), dashboard
  "Backend logs". Loki API: `127.0.0.1:53100`. Alloy UI: `127.0.0.1:52345`.
- `LAB_LOG_LEVEL` (default `INFO`) sets the level. Every API response carries `X-Request-Id`
  (the caller's when it is 1 to 64 characters of `A-Za-z0-9._-`, otherwise generated); consumer lines
  carry `event_id`, `event_type` and `queue`.
- `scripts/smoke_observability.sh` runs the API, forces an unhandled error and finds the line
  in Loki. `LAB_TEST_LOKI_URL=http://127.0.0.1:53100 uv run pytest tests/observability` does
  the same check for the file-to-Loki leg only.
- Truncate with `: > logs/backend.log` only while Alloy is stopped; rotation is not handled.

See [the observability note](docs/study/observability.md).
