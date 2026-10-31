# Ship exactly once when the carrier's answer is uncertain

Shipping hands a packed order to a carrier and then removes the stock from the
warehouse. The carrier is an external system: a call can succeed, fail, or
succeed while the response is lost. The WMS must never decide "it failed" from a
timeout, and must never ship or decrement twice.

## Follow the happy path

1. `ShipOrder(transaction, carrier).execute(order_key)` locks the order, requires
   `PACKED` with exact package totals, and **commits** one `ShippingAttempt`
   (status `PENDING`) whose ID is derived from the order. The package set is frozen.
2. No WMS transaction is open while the carrier is called.
3. `ReconcileShipment` asks the carrier `find_shipment` first. A receipt finalizes;
   an authoritative `None` (NOT_FOUND) calls `create_shipment` with the **same**
   attempt ID and payload.
4. Finalization is one transaction: lock order, then stock; validate the receipt
   against owner, order, attempt ID and exact package set; decrement
   `on_hand`, `allocated` and `picked` once; move the order `PACKED` -> `SHIPPED`;
   mark the attempt `SHIPPED` with its tracking number.

A timeout or unavailable lookup leaves the attempt `UNKNOWN`. Calling `ShipOrder`
or `ReconcileShipment` again resumes the same attempt; there is no way to make a
second one (primary key per order, unique attempt ID).

## Why this shape

| Problem | Answer |
|---|---|
| Carrier call succeeded, response lost | Attempt stays `UNKNOWN`; lookup finds it; no second create |
| Request never arrived | Lookup says NOT_FOUND; retry create with the same ID |
| WMS crashes after committing the attempt, before the call | Attempt is `PENDING`; the next call reconciles it |
| Two workers ship the same order | Order lock serializes; the loser sees the stored attempt or `SHIPPED` |
| Finalization fails halfway | One transaction: stock, order and attempt roll back together |
| Wrong or foreign receipt | Rejected before any write |

Stock decrements only inside finalization, guarded by `PACKED` plus the stored
attempt state, so repeated or concurrent reconciliation is a no-op once `SHIPPED`.
Reservation rows keep their historical quantities; `balance.packed` is a legacy
count and is untouched.

## Trade-offs and honesty

- **Idempotency is a contract on the carrier port**, not a property of carriers.
  The fake carrier deduplicates by attempt ID in its own tables and transactions
  (no foreign keys to WMS tables, durable across adapter restarts). A real carrier
  that cannot deduplicate needs a different recovery design (lookup by reference,
  or manual review). `find_shipment` must return `None` only for authoritative
  NOT_FOUND; treating "unreachable" as NOT_FOUND would create duplicates.
- **Commit before calling** costs one extra transaction and creates a visible
  `PENDING` state, but it is what makes crash recovery possible.
- **`ShipOrder` returns an `UNKNOWN` attempt instead of raising.** An uncertain
  carrier answer is a valid, persisted state rather than an error, so callers must
  inspect `attempt.status` and retry through `ReconcileShipment` (or `ShipOrder`
  again); the price is that "no exception" does not mean "shipped".
- **Order-level receipt only**: no partial shipments, returns or label purchase.
- Application-level immutability of the payload; arbitrary SQL can bypass it.

## Verify and challenge

```sh
LAB_TEST_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab \
  uv run pytest tests/shipping -q
```

Think before reading the tests:

- The carrier created the shipment, then your process died. What exactly does the
  next run read, and why can it not create again?
- Why must the lookup distinguish "not found" from "could not ask"?
- Why can finalization be retried safely but the carrier call cannot be inside it?

## Roll back safely

`uv run alembic downgrade 0004_packing` refuses while any attempt or `SHIPPED`
order exists. Reconcile first; code rollback removes `src/shipping/`, its tests,
this note, migration `0005`, and the `SHIPPED`/`ship` additions in orders and
inventory.
