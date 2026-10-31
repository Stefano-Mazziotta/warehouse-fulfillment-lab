# Allocate one stock balance without overselling

A warehouse must not promise the last unit to two workers. The immutable domain
snapshot enforces arithmetic; the PostgreSQL transaction protects the interval
between reading availability and writing the new reservation.

## Trace the operation

1. `AllocateInventory` opens an application-owned `InventoryTransaction`.
2. The PostgreSQL adapter selects the complete client/SKU/warehouse/location key
   with `FOR UPDATE`. An absent balance raises `InventoryNotFound`; no stock is
   created implicitly.
3. `InventoryBalance.allocate` rejects invalid quantities and insufficient stock.
4. The adapter updates only a balance locked in that transaction. A clean context
   exit commits; any exception rolls back; the connection always closes.

The existing `InventoryRepository` stays read-only. Transactional writes use a
separate port rather than quietly adding write permissions to query adapters.
Only infrastructure imports SQLAlchemy; domain/application remain standard-library
Python. Alembic installs the composite primary key and database checks protecting
nonnegative quantities, allocated ≤ on hand, and picked ≤ allocated.

## Explain the race

Under PostgreSQL READ COMMITTED, worker B waits while A holds the row lock.
After A commits, B's locking read sees the updated row, not the original
availability. With one unit, A commits one reservation and B raises
`InventoryError`. `test_last_unit_waits_on_lock_then_rechecks_committed_stock`
uses two real sessions and observes `pg_blocking_pids` before releasing A;
launching two threads without proving a wait would be weaker evidence.

The adapter explicitly selects READ COMMITTED rather than relying on an engine's
ambient isolation configuration. Locks end at transaction completion, not when
an immutable Python object is returned. Save refuses rows not locked through
this transaction.

## Run the proof

Follow the PostgreSQL commands in [the README](../../README.md). The configured
suite checks rollback after a saved update, invalid/missing operations, complete
key isolation, direct SQL constraint failures, and upgrade/downgrade/re-upgrade.
Tests create fresh UUID-named schemas and destroy only their own schema. No
SQLite substitute, remote database, or unrelated Docker service is involved.

## Boundaries to defend in an interview

- This reserves one balance, not all lines of an order. Looping separate calls
  cannot provide all-or-nothing multi-balance allocation.
- Retrying a successful call reserves again. Idempotency and reservation identity
  belong in the later order flow; this is not a public allocation endpoint.
- Locks protect participating database transactions, not physical stock accuracy.
  Counts and reconciliation remain separate warehouse responsibilities.
- A connection failure during commit can leave an uncertain outcome; blindly
  retrying is unsafe without durable operation identity.
- A future multi-row transaction needs consistent lock ordering to reduce deadlocks.
  This adapter does not implement that order-level orchestration.

Challenge: if a worker's connection drops after PostgreSQL commits but before the
worker receives confirmation, what information would make a retry safe?
