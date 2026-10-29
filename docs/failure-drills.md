# Failure drills

Eight runnable exercises. Each one injects a real failure into the running lab stack and shows
you what protected the data. They follow the same rule as the [demo](demo.md): you predict
first, then the script shows the evidence, then it reveals the explanation.

Every drill prints, in this order:

1. `SCENARIO`: the business situation, in warehouse terms.
2. `PREDICT`: one question. On a terminal the script now waits for Enter. Write your answer down.
3. `EVIDENCE`: the failure is injected for real; you see the rows, locks, queues or logs.
4. `VERDICT`: `[ok]` or `[FAIL]` per invariant. A `[FAIL]` means the protection did not hold, and
   the script exits with code 1.
5. `REVEAL`: the invariant, the mechanism, what breaks without it, and the trade-off.

The answers below are collapsed on purpose. Try the question before you open one.

## Run them

```sh
docker compose -p warehouse-fulfillment-lab up -d --wait postgres rabbitmq valkey dynamodb-local
export LAB_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
uv run alembic upgrade head          # once
scripts/drills/run_drill.sh 1        # interactive: pauses at the question
scripts/drills/run_drill.sh all --no-pause
```

| Flag | Effect |
| --- | --- |
| `<n>` or `all` | Run drill 1 to 8, or every drill in order (each with its own run id). |
| `--no-pause` | Print the question but do not wait. This is also the default when stdin is not a terminal. |
| `--keep-data` | Leave this run's rows so you can query them yourself. |
| `--cleanup RUN_ID` | Delete a kept run's rows (and nothing else), then exit. |

If a service is down, the script names it, prints the `docker compose ... up -d` command and
exits with code 2. Drills 1 to 4, 6 and 8 run in the script's own process. Drills 5 and 7 start
host child processes (and drill 7 also stops a container); see the safety notes below.

### What the drills touch, and what they never touch

- Every row belongs to one unique client `D<run id>`. Cleanup deletes only that client's rows,
  its inbox rows (matched by consumer name or id prefix), its DynamoDB item, and its Valkey key.
- Drill 5 creates a RabbitMQ queue named `drill.<run id>` (plus its `.retry` and `.dlq`
  queues) bound to an event type that exists only for that run, and always deletes them.
  The real `orders.projection` queue never sees a drill message.
- Child processes (drill 5's two crashing workers, drill 7's API) are real interpreters whose
  PIDs the script tracks; it never kills anything by name. Their stderr goes to `logs/backend.log`.
- Drill 7 runs `docker compose -p warehouse-fulfillment-lab stop valkey` and, in a `finally`
  block, `up -d --wait valkey`. If you interrupt it with `kill -9` the container stays stopped:
  run `docker compose -p warehouse-fulfillment-lab up -d --wait valkey`.
- Other projects' containers are never addressed: Compose is always called with `-p warehouse-fulfillment-lab`.

## The eight drills at a glance

| # | Drill | Invariant | Mechanism | Source | Interview talking point |
| --- | --- | --- | --- | --- | --- |
| 1 | Two workers allocate the last unit | `allocated <= on_hand`: one winner | row lock (`SELECT ... FOR UPDATE`) in the allocation transaction | `src/orders/application/allocate_order.py`, `src/orders/infrastructure/postgres_order_transaction.py` (`lock_stock`) | "How do you stop overselling? Why a lock and not a check-then-write?" |
| 2 | Carrier times out after creating the shipment | one order, one shipment, one stock decrement | attempt committed before the call, `UNKNOWN`, lookup by attempt id before any create | `src/shipping/application/ship_order.py`, `reconcile_shipment.py`, `src/shipping/infrastructure/postgres_fake_carrier.py` | "A call to a third party times out. Did it happen?" |
| 3 | Webhook delivered twice | one event id, one effect | stored raw event, then inbox row (PK consumer + message id) in the same transaction as the effect | `src/integrations/application/receive_channel_event.py`, `src/messaging/application/idempotent_consumer.py` | "At-least-once delivery: where do you put idempotency?" |
| 4 | Events arrive out of order | projected status never regresses | lifecycle stage as version, conditional write `stage < :new` | `src/orders/application/project_order_event.py`, `src/orders/infrastructure/dynamodb_order_projection.py` | "No sequence numbers: how do you order events?" |
| 5 | Crash after commit before ack; relay crash mid-batch | at-least-once delivery, exactly-once effect | ack after commit, inbox in the same commit, publish-then-mark outbox | `src/messaging/infrastructure/rabbitmq_consumer_runner.py`, `src/messaging/application/outbox_relay.py` | "What if the consumer dies between commit and ack? And the relay between publish and mark?" |
| 6 | A lost event repaired by reconciliation | the warehouse converges on the channel | checkpoint + keyset cursor + overlap window through the normal ingest path | `src/integrations/application/reconcile_channel_orders.py`, `src/integrations/infrastructure/postgres_reconciliation_transaction.py` | "Webhooks are hints. How do you know you did not miss one?" |
| 7 | Valkey is down | the cache never changes an answer or blocks a write | cache errors are misses, 5 s cooldown, throttled warning, allocation never reads the cache | `src/orders/application/caching_order_queries.py`, `src/orders/infrastructure/valkey_order_summary_cache.py` | "What happens when the cache dies? What is the failure mode of your cache?" |
| 8 | EDI document arrives twice | one partner order number, one order | inbox key sender + ISA13, then idempotent `CreateOrder` with payload comparison | `src/integrations/edi/order_intake.py`, `src/orders/application/create_order.py` | "How do you make EDI intake idempotent? What if the payload changed?" |

Each drill also has a gated test (`tests/drills/test_drills_live.py`, `LAB_TEST_DRILLS=1`) that
runs it unattended and re-checks the invariant straight from PostgreSQL, DynamoDB or Valkey.

## Drill 1: two workers allocate the last unit

**Scenario.** The bin holds 1 unit. Orders A and B each ask for it and two workers allocate
them at the same moment. The script freezes worker A right after it locked the balance, so you
can watch worker B.

```sh
scripts/drills/run_drill.sh 1
```

**Question.** What does worker B do while A is frozen: read `available = 1` and also allocate,
fail at once, or wait? Who ends up with the unit, and what is the final `available`?

**Evidence to look for.** A `pg_stat_activity` row for worker B with `wait_event_type = Lock`
whose blocker is worker A's backend pid; a third connection that still sees `allocated = 0`
(A has not committed); one `WON`, one `lost`; one reservation row.

<details><summary>Answer</summary>

B waits. Both workers run `SELECT ... FOR UPDATE` on the same balance row; the second one
queues behind the first until it commits. Then B re-reads the committed row (READ COMMITTED
re-evaluates the locked row), sees `available = 0` and the order is refused with
"Insufficient stock". Final: `on_hand 1, allocated 1, available 0`, one reservation, order A
`ALLOCATED`, order B still `CREATED`.

Without the lock, both read `available = 1`, both write `allocated = 1` and both orders get a
reservation: a lost update, one unit promised twice. The `allocated <= on_hand` check
constraint would not catch it, because each write on its own is valid.

Trade-off: correctness by serialization. A hot SKU makes workers queue (and locking several
SKUs needs a fixed order, which `lock_stock` provides by sorting, to avoid deadlocks).
Optimistic locking (version column, retry) trades waiting for retries.

</details>

## Drill 2: the carrier times out after creating the shipment

**Scenario.** The order is packed and `shipOrder` calls the carrier. The carrier commits the
shipment but the response is lost; we only see a timeout. A restarted worker then retries.

```sh
scripts/drills/run_drill.sh 2
```

**Question.** Right after the timeout, what are the order status, the shipping attempt status
and the stock? When the worker retries, is a second shipment created? How many times is stock
decremented?

**Evidence to look for.** After the loss: order `PACKED`, attempt `UNKNOWN`, 1 row in
`fake_carrier_shipments`, stock `3/3/3`, no `OrderShipped` event. After the retry:
`create calls: 0`, order and attempt `SHIPPED`, still 1 carrier shipment, stock `0/0/0`, one
`OrderShipped` event.

<details><summary>Answer</summary>

The attempt row is committed with a deterministic id before the carrier is called, and no WMS
transaction is open during the call. A timeout does not mean failure: the attempt becomes
`UNKNOWN` and the order stays `PACKED` with its stock untouched. `ShipOrder` returns the
`UNKNOWN` attempt; it does not raise. The retry goes through `ReconcileShipment`, which asks the
carrier `find_shipment(attempt_id)` first; it finds the shipment and finalizes: stock leaves
(`on_hand` and `allocated` drop by 3, `picked` returns to 0), the order becomes `SHIPPED`, and
`OrderShipped` is written to the outbox, all in one transaction. A create would happen only after
an authoritative "not found", and with the same attempt id.

Without this, a naive retry creates a second label and parcel, or failing the order hides a
parcel that physically exists.

Trade-off: it needs a carrier that deduplicates on our id or supports lookup by it (the lab's
fake does; real carriers vary), and the order is stuck in `UNKNOWN` until something retries.

</details>

## Drill 3: a webhook is delivered twice

**Scenario.** The sales channel POSTs "order created" to `/webhooks/sales-channel`. It did not
see our `202`, so it sends the same event id again. Then five copies of another event arrive at
the same instant.

```sh
scripts/drills/run_drill.sh 3
```

**Question.** What does the second delivery return, and what is in the database afterwards
(stored events, inbox rows, orders)? What decides who wins when five copies race?

**Evidence to look for.** `HTTP 202 CREATED` then `HTTP 202 DUPLICATE_EVENT`; one row in each
table; `UniqueViolation on constraint inbox_messages_pkey` when the script inserts the inbox row
by hand; `{'CREATED': 1, 'DUPLICATE_EVENT': 4}` for the burst.

<details><summary>Answer</summary>

The second delivery is acknowledged with `202` and outcome `DUPLICATE_EVENT`, so the sender stops
retrying, and nothing changes: one `integration_events` row, one inbox row, one order. The raw
event is stored first with `ON CONFLICT DO NOTHING` on its id. The handler then runs inside
`IdempotentConsumer`: it inserts `(consumer, message id)` in the inbox in the SAME transaction as
the order. For five simultaneous copies, the inbox primary key decides: the losers block on the
unique index until the winner commits, then conflict and skip. The database rejects a duplicate
inbox row even when you write it by hand.

Without the inbox every redelivery would re-apply the effect. A "check, then insert" is not a
substitute: two requests can both pass the check.

Trade-off: the inbox grows without retention, and answering `202` to a duplicate also hides a
sender that reuses event ids for different content.

</details>

## Drill 4: events arrive out of order

**Scenario.** The DynamoDB read model is fed by lifecycle events. `OrderShipped` arrives first,
then `OrderPacked`, `PickingCompleted` and finally `OrderAllocated`; `OrderShipped` is then
delivered a second time.

```sh
scripts/drills/run_drill.sh 4
```

**Question.** After each arrival, which stage and status does the projection show? Can an old
event move the order back to `ALLOCATED`? Which late event still adds something, and what
absorbs the last duplicate?

**Evidence to look for.** A five-row table: stage stays `4`, status stays `SHIPPED` on every
row; only the first row has `status advanced? yes`; the `warehouse` column fills in when
`OrderAllocated` arrives late; the fifth row says `no (inbox)`.

<details><summary>Answer</summary>

The status never regresses: the final stage is the maximum event stage, `4`, `SHIPPED`. The
events carry no version, so the lifecycle position (allocated 1, picked 2, packed 3, shipped 4,
cancelled 5) is the version. `apply` does two writes: immutable facts (warehouse, line count,
package count, tracking number) are set unconditionally, and status plus stage are set only
under `attribute_not_exists(stage) OR stage < :stage`. A stale event fails that condition and
changes nothing, but its facts still land: the warehouse appears when `OrderAllocated` arrives
late. The repeated `OrderShipped` never reaches the projection; the inbox row for its message id
already exists.

Without the condition (last write wins), the late `OrderAllocated` overwrites `SHIPPED`.

Trade-off: stage ordering assumes each fact happens once and the lifecycle only moves forward
(it would break for re-opened orders). `CREATED` and `PICKING` emit no events, so the
projection cannot show them.

</details>

## Drill 5: a worker crashes after commit but before ack, and a relay crashes mid-batch

**Scenario.** Part A: a consumer commits its stock receipt to PostgreSQL and is killed with
`SIGKILL` before acknowledging the message. Part B: three events wait in the outbox; the relay is
killed after publishing two of them and before marking any row `PUBLISHED`. Stock receipts are the
effect: each event adds 1 to `on_hand`.

```sh
scripts/drills/run_drill.sh 5
```

**Question.** After the consumer crash, is the effect applied, and does the broker still hold the
message? When it is redelivered, is the effect applied twice? After the relay crash, what status
do the outbox rows have, how many messages are already in the broker, and what does stock end at
once everything recovered?

**Evidence to look for.** `child exit code -9` twice; after part A `on_hand = 1, inbox rows = 1,
queue ready = 1, consumers = 0`, then `[False]` for the redelivery; after part B
`{'PUBLISHED': 1, 'PENDING': 3}` with 2 messages in the broker, then 5 messages for 3 events and
a final row `5 deliveries, 3 applied, 2 absorbed, on_hand 4, inbox rows 4`.

<details><summary>Answer</summary>

Part A: the effect is applied (the commit happened) and the broker still holds the message,
because the ack never came and the connection dropped. The redelivery is absorbed: the inbox row
committed in the same transaction as the effect, so the handler is skipped and `on_hand` stays 1.
Part B: all three rows are still `PENDING` (the mark is part of the batch transaction, which died
with the process) although two messages are already in the broker. The recovery relay publishes
all three again, so the broker holds five messages for three events; the consumer applies three
and absorbs two. Stock is exactly the number of distinct events (1 + 3 = 4).

Without ack-after-commit a crash loses the work. Without the inbox every redelivery applies the
effect again. Marking before publishing would lose events the broker never received.

Trade-off: duplicates are normal, so every handler must be idempotent and the inbox needs
retention. The relay holds row locks while it publishes, so batches stay small and timeouts short,
and ordering per aggregate is best effort.

</details>

## Drill 6: a lost event repaired by reconciliation

**Scenario.** The sales channel is the source of truth for its orders. Three orders are placed
and the webhooks for two of them are lost. Later a fourth is lost too.

```sh
scripts/drills/run_drill.sh 6
```

**Question.** Does the warehouse notice anything is missing by itself? What do you run to repair
it, and what does a second run do when nothing is missing? What moves in the checkpoint table,
and when?

**Evidence to look for.** `channel orders 3, WMS orders 1` before; pass 1 `repaired 2`; pass 2
`repaired 0, already known 3` with the same cursor; pass 3 `repaired 1` and a cursor that moved
to the new order; `4` and `4` at the end.

<details><summary>Answer</summary>

Nothing notices: a lost webhook is silent. The reconciler pages the channel from its checkpoint
(`integration_checkpoints.cursor`, the keyset `(updated_at, id)` of the last order it saw),
starting an overlap window (5 minutes) before it, and feeds every order through the same
`ReceiveChannelEvent` path as a webhook. Reconciliation events have deterministic ids, so
re-reading is an inbox duplicate and does nothing: pass 2 changes nothing and the cursor stays.
The checkpoint advances only after the whole page was ingested, so a failure re-reads the page
instead of skipping an order. Pass 3 repairs only the new loss and moves the cursor.

Without reconciliation the order never ships and nobody knows. A strict `updated_at >
checkpoint` skips ties at page boundaries and orders committed late; the keyset cursor and the
overlap window cover both.

Trade-off: polling freshness is bounded by its period, the overlap makes every run re-read
recent history, and the per-client checkpoint row lock serializes runners.

</details>

## Drill 7: Valkey is down

**Scenario.** The order-summary cache is stopped for real (`docker compose ... stop valkey`)
while the API serves traffic. Ten reads and a brand-new order allocation hit the API during the
outage. The script restarts Valkey and verifies it afterwards.

```sh
scripts/drills/run_drill.sh 7
```

**Question.** Do the reads fail, slow down or return stale data? Does allocating stock ever look
at the cache? How many log lines will the outage produce for those eleven operations, and where
do you find them?

**Evidence to look for.** `10 reads ... ['ALLOCATED']`, the second order `ALLOCATED`,
`warnings in logs/backend.log during the outage: 1`, the JSON line with `"logger":
"orders.cache"`, and `healthy and refilled` after the restart.

<details><summary>Answer</summary>

Reads succeed from PostgreSQL with the correct status. The cache is a miss, never an error:
`CachingOrderQueries` swallows any cache failure and skips the cache for a 5 second cooldown, so
a dead server costs one short timeout per window, not one per request. Allocation reads and
locks PostgreSQL only and never consults the cache; the invalidation after the commit is best
effort. The Valkey adapter logs a single throttled WARNING (`cache unavailable; reads fall back to
PostgreSQL`) per 5 second window with the request id, instead of a stack trace per call; find it
in `logs/backend.log` or in Loki with `{service="backend"} |= "cache unavailable"`. When Valkey
returns, the first read after the cooldown fills it again.

Without this, a cache exception is a `500` on reads or a failed response after a committed write,
and an unthrottled warning floods the log exactly when you need to read it.

Trade-off: reads are slower during the outage and a lost invalidation can serve a stale summary
for up to the 30 second TTL. Valkey is not durable, so nothing may live only there.

</details>

## Drill 8: an EDI document arrives twice

**Scenario.** A partner sends a 940 (warehouse shipping order). The VAN delivers the identical
file twice. Later the partner resends it under a new interchange control number, and finally
sends the same order number with the quantity changed from 2 to 5.

```sh
scripts/drills/run_drill.sh 8
```

**Question.** For each of the four documents: applied, treated as a duplicate, or refused? How
many orders and inbox rows exist after each? What is the idempotency key, and why is the sender
part of it?

**Evidence to look for.** A four-row table: `applied`, `duplicate (inbox)`, `applied`,
`REFUSED: Order key already exists with a different payload`; orders stay `1`, line quantity stays
`2`, inbox rows go `1, 1, 2, 2`.

<details><summary>Answer</summary>

1. The first 940 is applied: one order, one inbox row keyed `<sender>:<ISA13>`.
2. The exact resend has the same key: the inbox drops it before any business code runs.
3. A resend under a new control number is a new key, so it reaches `CreateOrder`; that use case
   is idempotent for an identical payload, so it changes nothing (and the second inbox row is
   committed). It counts as "applied" at the inbox level and as a no-op at the order level.
4. The amended document reaches `CreateOrder` with a different payload for an existing order
   key: it is refused, nothing is overwritten, and its inbox row rolls back, so a corrected resend
   is not blocked.

The sender is part of the key because a control number is only unique per sender: two partners
may both send `000000001`. Trade-off: a partner that resets its counter collides with old keys;
an amendment needs a human or a defined flow (real EDI would use a change order); and the sender
comes from the unauthenticated ISA06 in this lab.

</details>

## Interview prompts these drills prepare

1. Two workers allocate the last unit. Walk through what each does and what the database does.
2. The carrier timed out. How do you know whether the shipment exists, and who decides?
3. Why is the inbox row written in the same transaction as the effect?
4. Events arrive out of order and carry no sequence number. What do you use as the version?
5. The consumer crashes after commit, before ack. The relay crashes after publish, before mark.
   What do you get in each case, and which side must be idempotent?
6. A webhook is lost. How do you find out, and what makes the repair safe to run twice?
7. The cache is down. What does the user see, and what does the operator see?
8. The partner resends an order with a changed quantity. What should the system do?

## Known limits (honest list)

- The carrier, the sales channel and the "VAN" are the lab's fakes; the fault flags
  (`lose_next_create_response`, `webhooks.drop`) are how a real network would misbehave, not
  proof about any real carrier.
- Drill 7 stops the lab's real Valkey container, so run it when nothing else is using the lab.
- Drill 5 kills child processes with `SIGKILL` from the same machine; that proves what the
  database and broker keep, not behavior under a network partition.
- The relay used in drill 5 is the demo's client-scoped worker class: the lab still has no
  production relay entry point.
- Not drilled because the lab does not model them: physical versus database inventory drift,
  one package of an order failing while another ships, two warehouses fulfilling one order.
