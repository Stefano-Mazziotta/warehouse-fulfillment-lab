# Decision

Allocate and cancel an order in one PostgreSQL transaction, locking the order
before its candidate inventory balances.

## Context

The first inventory exercise safely allocates one balance, but does not record
which order owns a reservation. A multi-line order needs all its required stock
or none, and a repeated request must not promise the same stock twice.

## Problem

Separate commits can leave a partially allocated order after shortage or failure.
Concurrent requests can oversell unless availability is checked while holding
locks. Cancellation must not release a different order's promises.

## Options

- Loop single-balance use cases: simple reuse, but breaks atomic order allocation.
- Optimistic versions plus retries: viable, but requires conflict detection across
  every affected stock row and order state, with more retry orchestration.
- One transaction with deterministic row locks: directly protects this bounded
  local consistency boundary; competing work waits.

## Decision

Use READ COMMITTED and a fresh transaction per use case. Lock the owner-scoped
order first, then all matching owner/warehouse/SKU balances in ascending SKU and
location order using FOR UPDATE, without SKIP LOCKED. Aggregate duplicate-SKU
demand, validate the full order, then distribute by ascending line/location IDs.
Commit stock, line-attributed reservations and state once. Cancel follows the
same lock ordering and releases only that order's unpicked reservation amounts.

Create uses INSERT ON CONFLICT DO NOTHING RETURNING, then reads the locked order
and compares canonical immutable payloads. Identical retries return current state;
conflicting payloads fail. The RETURNING result, not driver rowcount truthiness,
distinguishes an insert from a conflict.

## Why

The locked order state is the idempotency guard. Locked inventory is the shared
scarce resource. The transaction is the all-or-nothing boundary. Composite
foreign keys tie reservation owner, warehouse and SKU to both the line and stock.

## Trade-offs

- Locking all candidate locations can increase contention, including unused bins.
  It keeps selection and lock ordering explicit rather than optimizing prematurely.
- READ COMMITTED may omit stock inserted after the candidate query. A concurrent
  replenishment can therefore require a later allocation retry; it cannot cause
  overselling through this path.
- Cancelled reservation rows are retained as history, so queries must use order
  state to determine activity rather than summing all rows.
- Constraints protect identity and quantity bounds; application transactions still
  own cross-row reservation totals. Arbitrary SQL writers are not business APIs.

## Consequences

Missing orders raise `OrderNotFound`; invalid transitions, shortages and payload
conflicts raise `OrderError`. Database and domain errors roll back all writes.
Picking/packing/shipping, stock movements and replenishment are outside this slice.
A future picking capability must track reservation-level picked quantities and
close cancellation at startPicking, rather than guessing from a balance total.
