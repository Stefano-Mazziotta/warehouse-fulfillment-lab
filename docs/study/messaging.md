# Messaging: outbox, inbox and honest delivery guarantees

Study note for the `messaging` capability. Read it, then try to break it with the
failure drills at the end before reading the code.

## The problem: two systems, one fact

`FinishPacking` changes PostgreSQL and the rest of the world must hear "order packed".
Publishing to a broker inside the same use case has no good ordering:

| Order | Failure | Result |
|---|---|---|
| commit, then publish | crash between | state changed, nobody told (lost event) |
| publish, then commit | commit fails | world told about something that never happened |

A broker and a database cannot share one transaction. So we make the event a row.

## Transactional outbox

`EventRecorder.record_event` inserts into `outbox_messages` on the SAME connection as
the state change. One commit makes both durable; one rollback removes both. The
Postgres transaction that already serves orders, picking, packing and shipping
implements the port, so domain and application code never import SQLAlchemy.

- Recorded: `OrderAllocated`, `OrderCancelled`, `PickingCompleted`, `OrderPacked`, `OrderShipped`.
- Only when the state actually changes. An idempotent retry (already allocated, packed,
  shipped) takes the early return and records nothing.
- `message_id` is derived (`OrderShipped:owner:order`). Each fact happens once per
  order, so the ID is stable, consumers can dedupe on it, and the primary key is a
  safety net against double recording. Each part is percent-encoded, so a `:` inside a
  client or order ID cannot make two different orders share an ID.

## The relay and at-least-once delivery

`OutboxRelay.run_once` claims due `PENDING` rows, publishes through the
`MessagePublisher` port, then marks them `PUBLISHED`, all in one transaction.

The unavoidable gap: the broker accepts the message, then the process dies before the
commit. The row is still `PENDING`, so the next run publishes it again. That is
**at-least-once**: duplicates are normal, loss is not. Exactly-once delivery does not
exist across two systems; we get exactly-once EFFECT by making consumers idempotent.

### Failures, backoff, DEAD

A `PublishFailed` increments `attempt_count`, stores `last_error` and schedules
`next_attempt_at = now + min(base * 2^(n-1), cap)`. After `max_attempts` failures the
row becomes `DEAD`: it stays visible for a human and the relay never touches it again
(the outbox equivalent of a dead-letter queue). One poison message does not block the
others in its batch. Clock and policy are injected, so the schedule is tested without
sleeping.

### Why SKIP LOCKED here but not in stock allocation

- **Allocation** must be a *serialized* decision on one specific row. If two orders want
  the last unit, the second must WAIT and re-read the winner's result. Skipping would
  let it decide on stale or missing data. So: `FOR UPDATE`, deterministic lock order.
- **The relay** needs *any* work, not a particular row. A locked row means another relay
  is already delivering it. Waiting would just serialize relays; skipping lets N relays
  drain the queue in parallel without double-claiming.

Trade-off: the claim lock is held during `publish`, so a slow broker holds row locks.
Keep batches small and publisher timeouts short. A lease column (claimed_until) avoids
long locks but adds a second state to reason about. Ordering across relays is
best-effort only.

## Inbox and the idempotent consumer

`IdempotentConsumer` inserts `(consumer_name, message_id)` into `inbox_messages` and
runs the handler in ONE transaction.

- Duplicate delivery: the insert conflicts, the handler is skipped.
- Handler fails: everything rolls back, including the inbox row, so redelivery retries.
- Two concurrent copies: the second waits on the unique index, then becomes a no-op
  (or proceeds if the first rolled back).
- The inbox is per consumer; a projection and a notifier each process the same message.

**Limit: no ordering.** At-least-once with retries, several relays and redelivery
reorders messages. The inbox dedupes; it does not sort. A handler that stores "latest
status = X on arrival" can end up with a stale value when `OrderPacked` overtakes
`OrderAllocated`. Safe patterns: keep sets of facts, compare a monotonic version, or
fetch current state from the source of truth. The tests use an order-insensitive handler
to show the safe shape.

A handler's effects must live in the same database as the inbox row. If the effect is an
external call (email, carrier), the inbox cannot make it atomic: that needs its own
idempotency key, as in the shipping attempt ID.

## RabbitMQ transport

`RabbitMqPublisher` and `RabbitMqConsumerRunner` (pika, in `messaging/infrastructure`)
implement the existing ports; domain and application never import `pika`.

- **Publisher confirms + `mandatory`.** A plain `basic_publish` only means the bytes left
  our socket. A confirm means the broker took responsibility (persisted a persistent
  message to a durable queue); a `nack` means it refused. `mandatory` returns messages no
  queue is bound for, which the broker would otherwise drop silently. Every one of these,
  plus connection errors and timeouts, becomes `PublishFailed`, so the relay backs off and
  keeps the row. Consequence: an event with no bound queue is retried, then DEAD.
- **Topology** (`rabbitmq_topology.py`): durable topic exchange `fulfillment.events`,
  routing key = event type, one durable queue per consumer name, `<queue>.retry` and
  `<queue>.dlq`. Declaring again is a no-op; declaring with other arguments is rejected.
- **Manual ack after commit.** The runner acks only after `IdempotentConsumer.handle`
  returned, i.e. after the inbox row and the effects committed. Acking first would turn a
  crash into LOSS; acking after turns it into a DUPLICATE, which the inbox absorbs.
- **Redelivery.** If the worker dies between commit and ack, the broker requeues the
  message and the inbox makes the second run a no-op. Broker redelivery plus inbox gives
  effectively-once EFFECTS, never exactly-once DELIVERY.
- **Retry and DLQ.** A failing handler does not crash the worker: the message is
  republished to `<queue>.retry` (its TTL is the delay, after which it dead-letters back
  to the work queue) with `x-attempt` incremented. After `max_attempts` handler runs it
  goes to `<queue>.dlq` with `x-attempt` and `x-last-error`, and the original is acked.
  Unreadable bodies skip retries. Trade-off: republish-then-ack is not atomic, so a crash
  in between duplicates the message (again absorbed by the inbox); the DLQ needs a human
  or a replay tool, which the lab does not build.
- **Prefetch** bounds unacked messages per consumer, so a slow handler cannot hoard the
  queue and memory stays bounded.
- **Ordering** is still not guaranteed: retries reorder messages by design.

## Events plus reconciliation

The outbox makes loss impossible for events we record, but it does not make systems
agree: consumers can be down for days, DEAD rows exist, schemas drift, and a downgrade
of the migration discards undelivered rows. Events are the fast path; periodic
reconciliation (compare current state, replay by `updated_at` or cursor) is the safety
net. Never reason "the event was published, so the other system is in sync".

## Failure drills

1. Kill the relay after `publish` but before the commit. What do consumers see?
2. The broker is down for an hour. When does each message turn `DEAD`? Is that too soon?
3. Two relays start together with 10 000 pending rows. Why is nothing published twice
   by the relays themselves, and why can a consumer still see a message twice?
4. A consumer handler calls an external API and then fails. What does the inbox guarantee?
5. `OrderCancelled` arrives before `OrderAllocated`. Which handler design survives?
6. Should `PUBLISHED` rows be deleted? What would break if you did it too early?
7. The broker is up but the consumer's database is down for ten minutes. Where do the
   messages wait, and what does `max_attempts` x retry delay decide?
8. Kill the worker between commit and ack. Prove (with the test) that the effect happens
   once.
