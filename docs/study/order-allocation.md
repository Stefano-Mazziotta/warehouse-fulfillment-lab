# Reserve an entire order, or nothing

Order allocation promises stock to one owner's order in one warehouse. It does
not move physical stock. Each reservation records which order line owns which
units at a location, so cancellation can release its own promises, not another
order's units.

## Follow the happy path

1. `CreateOrder.execute(Order(...))` stores immutable lines and warehouse.
2. `AllocateOrder.execute(OrderKey(...))` locks the order, then every candidate
   balance for its owner, warehouse and SKUs, ordered by SKU and location ID.
3. The use case totals duplicate-SKU demand before checking availability. If all
   demand fits, it distributes stock to ascending line IDs and location IDs.
4. Balance updates, reservation inserts and `ALLOCATED` state commit together.
5. `CancelOrder.execute(key)` locks in the same order and releases only this
   order's reservation quantities, transitioning to `CANCELLED` in that commit.

Application use cases depend on the `OrderTransaction` Protocol, not SQLAlchemy.
`PostgresOrderTransaction` owns a fresh connection and the single commit/rollback.
It does NOT call the earlier single-balance `AllocateInventory` use case in a loop.

## What counts as a retry?

| Operation | Same request again | Different request using same identity |
|---|---|---|
| Create | Existing order, including its current state | `OrderError` |
| Allocate | Already `ALLOCATED`: no writes | `CANCELLED`: `OrderError` |
| Cancel | Already `CANCELLED`: no writes | Only CREATED/ALLOCATED currently supported |

Create compares warehouse and canonical line-ID order, not the caller's tuple
order. New orders must be CREATED; callers cannot submit an allocated snapshot
to bypass the business operation. Keys are owner-scoped: another owner's order
with the same order ID is a different order.

Cancelled reservations stay as history. Their order's CANCELLED status makes
them inactive; summing every historical reservation row is NOT an active-stock
query. In this slice, only reservations attached to ALLOCATED orders are active.
Picked/packed/shipped lifecycle states are deliberately not introduced yet.

## Trace a split allocation

An order has line `a: SKU-X × 1` and line `b: SKU-X × 2`. Location `a` has two
available units; location `b` has three. Reservations become:

```text
line a → location a × 1
line b → location a × 1
line b → location b × 1
```

The order needs three units, not two independent availability checks against the
same original snapshot. Stock identity includes owner, SKU, warehouse and location.
Composite foreign keys prevent attaching the line to another owner's, warehouse's
or SKU's stock, even through direct SQL.

## Reproduce the failure proofs

```sh
LAB_TEST_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab \
  uv run pytest tests/orders -q
```

Tests create and drop only their own random schemas in the disposable lab DB.
They prove shortage rollback, a fault after a reservation INSERT, a fault after
a cancellation stock UPDATE, creation retry conflicts, owner/warehouse isolation,
and actual blocked PostgreSQL sessions using `pg_blocking_pids`.

At READ COMMITTED, the loser waits for the row lock and then checks committed
stock/state. The same-order loser returns the winner's ALLOCATED order without
reserving twice. A different-order loser competing for the last unit fails
without side effects. No SKIP LOCKED means contention does not become a false
"stock missing" result.

## Explain it before extending it

- Why would two individually successful single-balance commits violate an
  all-or-nothing order promise?
- Why must cancellation use reservation ownership, rather than subtracting the
  order's requested quantity from whichever bin currently has stock?
- Why do different orders still need the same stock lock order?
- What changes when a picker has physically picked only part of a reservation?

Next: model partial picking and the cancellation cutoff; do not infer that
balance-level `picked` alone tells you which order was picked.
