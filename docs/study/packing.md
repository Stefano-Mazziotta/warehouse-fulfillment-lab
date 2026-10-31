# Reconcile physical packages before completing packing

Packing assigns already-picked units to physical packages. A packer may split
one reservation across boxes, but cannot pack the same units twice or finish
while any ordered unit is missing. This lab completes an entire order, not a
partial shipment.

## Follow the happy path

1. Complete picking: the order must be `PICKED`.
2. Construct immutable `PackageItem` entries using order, line and complete stock
   identity. Construct a `Package` with an order-scoped ID, positive integer
   weight in grams, dimensions in millimetres, and nonempty contents.
3. Call `AddPackage(transaction).execute(package)` for each physical package.
4. Call `FinishPacking(transaction).execute(order_key)` once all units are packed.
   Exact reservation and line totals are required before moving to `PACKED`.

Both use cases live in `src/packing/application/` and accept the same fresh
`PostgresOrderTransaction` factory as picking. Run `uv run alembic upgrade head`
to install migration `0004_packing`. There is no HTTP adapter yet.

## Trace the consistency boundary

```text
Order lock
  → Read owned reservations and existing packages
  → Validate PackingConfig quantities
  → Insert package header and contents, or finish order
  → Commit together
```

`PackingConfig` owns conservation; `Order.finish_packing()` owns the state
transition. The orders domain does not import packing. The packing-specific
transaction Protocol extends the inward order port, while the existing
PostgreSQL adapter persists both capabilities atomically.

The order lock serializes all application package writes and packing completion.
After waiting, a second transaction re-reads committed packages before validating
its own addition. No stock row lock is needed because packing does not change
inventory balances or picking progress. The picked reservation retains its
accounting source; physical staging-bin transfers are outside this model.

## Rules and deliberate tradeoffs

| Rule | Consequence |
|---|---|
| Full reservation identity | Duplicate SKU lines and different source bins cannot substitute for each other. |
| Immutable package ID and payload | Identical canonical retry is a no-op, even after `PACKED`; changed payload is rejected. |
| Canonical contents | Entry ordering does not change retry identity; duplicate reservation entries are rejected rather than merged. |
| Positive exact integers | Booleans, fractional measurements and zero quantities are invalid domain input. |
| Cumulative bounds | Each reservation's packed total cannot exceed its picked or reserved quantity. |
| Exact finish | Every owned reservation must be fully picked and packed; reservation totals must cover every order line. |
| No new packages after finish | Existing identical retries remain safe, but new IDs cannot bypass the state cutoff. |

PostgreSQL foreign keys enforce order/package ownership and the full reservation
source. Positive checks protect stored measurements and content quantities.
Cross-row quantity conservation and nonempty-package contents are application
invariants: bypassing the use cases with arbitrary SQL is not supported. There
are no edits, removals, carrier choices or balance-wide `packed` counter updates.
Those omissions keep this exercise focused; a later correction workflow would
need explicit rules rather than silently replacing package contents.

## Verify and challenge

```sh
LAB_TEST_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab \
  uv run pytest tests/packing -q
```

Tests use uniquely named disposable schemas. They exercise actual blocked
PostgreSQL writers, duplicate-SKU/source attribution, canonical retries,
overpacking, state cutoffs, rollback after header insertion and completion,
unchanged inventory, constraints, and migration downgrade locks.

Explain before reading the tests:

- Two packers each try to place the last two units into a different box. Why is
  checking only the incoming box insufficient?
- The transaction commits, but the packer loses the response. What makes a retry
  distinguishable from an accidental package-ID reuse?
- Every SKU total matches, but contents use the wrong order line or source bin.
  Why must completion still fail?

## Rollback safely

`uv run alembic downgrade 0003_picking` locks orders, reservations, packages and
contents before checking for information loss. It refuses when any package or
`PACKED` order exists, including inconsistent imported state. Reconcile first;
do not erase operational records merely to force a downgrade. Empty-package
schemas can downgrade and re-upgrade without losing existing picked progress.

Code rollback removes `src/packing/`, its tests and this guide, migration `0004`,
and the matching order status/transaction/schema, metadata registration and wheel
packaging changes. It must not remove earlier picking or allocation behavior.

Next: shipping will consume these reconciled physical packages. Carrier calls
and shipment reliability are not implemented by this slice.
