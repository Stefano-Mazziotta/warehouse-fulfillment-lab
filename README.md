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
as above, not inside the domain. Flask is deliberately not installed yet.

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
packages and shipping are not implemented yet.

## Order-owned partial picking

Run migration `0003_picking` with `uv run alembic upgrade head`. Start picking,
record cumulative picked targets per complete reservation identity, then complete
only when every order line is fully picked. Picking changes neither on hand nor
allocated stock. Cancellation is rejected once picking starts.

`StartPicking`, `RecordPick` and `CompletePicking` live in
`src/picking/application/` and share the order transaction factory above.
See [the picking walkthrough](docs/study/picking.md) for retry semantics,
concurrency proofs, scanner tradeoffs and the guarded downgrade.
