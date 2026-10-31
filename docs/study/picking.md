# Pick an order without counting a retry twice

Picking records the physical collection of already reserved units. Start picking
crosses the cancellation cutoff; completion certifies that every reserved unit
for every order line was picked. It does not ship stock or create packages.

## Quick path

1. Create and allocate an order through the order application use cases.
2. Call `StartPicking(transaction).execute(order_key)`.
3. For each reservation, call
   `RecordPick(transaction).execute(order_key, line_id, stock_key, target)`.
4. Call `CompletePicking(transaction).execute(order_key)` after all targets reach
   their reserved quantities.

Use `transaction = lambda: PostgresOrderTransaction(engine)` with a live engine.
The stock key includes owner, SKU, warehouse and source location. Read reservation
identities through `PostgresOrderTransaction.get_reservations(order_key)`;
the operation cannot borrow another line's or order's reservation.

## Cumulative targets, not scanner deltas

For a reservation of three units, targets `1, 1, 3` add stock-picked deltas
`1, 0, 2`. The repeated target is a no-op. A target of zero, a decrease, an
excess or a noninteger (including a boolean) is rejected.

This API sacrifices convenient independent scan increments for retry safety
without storing operation IDs. Two scanners sending target one do NOT mean two
units. A real delta-based scanner workflow would need an independently designed
operation identity and deduplication contract. An old target arriving after a
newer target is rejected, not silently interpreted as a successful retry.

| Operation | Allowed state and retry |
|-----------|-------------------------|
| Start | ALLOCATED becomes PICKING; retry in PICKING is a no-op |
| Record target | PICKING only; same current target is a no-op |
| Complete | PICKING with every reservation fully picked becomes PICKED; retry in PICKED is a no-op |
| Cancel | CREATED or ALLOCATED only; no cancellation from PICKING onward |

Picking increases only `InventoryBalance.picked`. On hand, allocated and
available stay unchanged: picked units remain allocated and physically in the
warehouse. Source location is an accounting reference; staging-bin transfers
are explicitly outside this model. Package contents belong to the next slice,
not to the balance-wide legacy `packed` counter.

## Transaction and failure boundary

All use cases lock the order first. RecordPick validates the owned reservation,
locks candidate stock in sorted SKU/location order, then saves the inventory
delta and reservation target in the same transaction. The order lock serializes
same-order picks, completion and cancellation. No stock lock can make a target
safe if the order/reservation is checked outside that boundary.

A fault after the balance UPDATE rolls everything back, so a retry starts from
the previous target. Real PostgreSQL tests prove the competing session actually
waits using `pg_blocking_pids`; thread timing alone is not the proof.

## Verify and roll back

```sh
LAB_TEST_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab uv run pytest tests/picking
```

Migration `0003_picking` defaults old reservations to zero and adds database
bounds. Downgrade to `0002_orders` refuses PICKING/PICKED orders or any nonzero
picked target. Its table locks prevent new progress between the guard and DDL.
Do not erase progress just to force a downgrade; reconcile the business state
first. Empty disposable test schemas can round-trip safely.

Rollback this work unit by downgrading only a reconciled disposable database,
then reverting picking use cases/tests/docs, order picking transitions,
reservation progress, transaction/schema extensions, the balance pick method,
migration0003 and picking package registration. Preserve order allocation and
cancellation from the preceding slice.

## Challenge yourself

- Why does a repeated target not decrement available stock?
- Which operation wins if cancellation and start picking overlap?
- What happens if one scanner submits target two after another reaches three?
- Why is a fully picked first line insufficient to complete a two-line order?

Next: model package contents and exact order-quantity reconciliation.
