# Warehouse fulfillment lab

A domain-first Python learning lab. The first inventory slice uses a `src/`
layout and stays independent of Flask, databases, and queues.

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
    adapters/       # InMemoryInventoryRepository
tests/inventory/    # Domain, application, adapter, and import-boundary tests
```

The application owns its persistence port. The in-memory adapter implements it
structurally; it does not need to inherit from the Protocol. Domain code knows
neither layer. This keeps the business capability visible instead of hiding it
inside global controllers/services/models directories.

```python
from inventory.adapters.in_memory import InMemoryInventoryRepository
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

## Next learning exercise

Implement allocation with tests before adding infrastructure. The immutable
balance and read-only memory adapter do **not** provide concurrent reservation
safety. Allocation, picking, packing, and shipping remain explicit exercises;
database atomicity and transaction boundaries need a separate implementation.
