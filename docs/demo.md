# End-to-end demo

> New to the layout? [System workflow in diagrams](system-workflow.md) draws the architecture and the flows this demo walks through.

One command runs a whole order through the lab: stock is received, the order moves from
`CREATED` to `SHIPPED` through the GraphQL API, and at every step you see where the data
lives: PostgreSQL (the truth), the outbox, RabbitMQ, the DynamoDB read model, the Valkey
cache and the Loki logs.

The script is prediction-first. Before each step it prints a question and waits. Write
down your answer, press Enter, compare. The answers are at the bottom of this page, in
collapsed sections; resist opening them first.

## Run it

```sh
docker compose -p warehouse-fulfillment-lab up -d --wait postgres rabbitmq valkey dynamodb-local loki alloy
export LAB_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
uv run alembic upgrade head          # once
scripts/demo/run_demo.sh             # interactive: pauses at each question
scripts/demo/run_demo.sh --no-pause  # unattended (also the default when stdin is not a terminal)
```

If a service is down the script prints which one and the exact `docker compose ... up -d`
command, then exits with code 2. Grafana (`grafana` service, <http://127.0.0.1:53000>, user
`lab`, password `lab-grafana`) is optional: the demo reads Loki's HTTP API directly, but
Grafana is where you would look at the same line by hand.

| Flag | Effect |
| --- | --- |
| `--no-pause` | Print the questions but do not wait. |
| `--keep-data` | Leave this run's rows in place so you can query them yourself. |
| `--cleanup RUN_ID` | Delete a kept run's rows (and nothing else), then exit. |

### What the script starts, and what it never touches

On the host, as plain child processes: the GraphQL API (Flask), the projection consumer
(`orders.infrastructure.order_projection_cli run`) and, from phase 4, an outbox relay
(`scripts/demo/outbox_relay_worker.py`). All stderr goes to `logs/backend.log`, the file
Alloy tails. When the demo ends it stops exactly the processes it started (it keeps their
PIDs; it never matches by name). Every row it creates belongs to a unique client
`demo-<run id>`, and the cleanup deletes only that client's rows, its DynamoDB item and its
Valkey key. Other projects' containers and data are never used.

The relay worker is a workaround for a gap: the lab has the `OutboxRelay` use case and the
RabbitMQ publisher, but no production entry point that loops them. The worker wires the same
classes the integration tests wire, and claims only the demo client's rows so it does not
publish anyone else's pending events.

## The flow

```text
                 GraphQL (X-Client-Id, X-Request-Id)
 learner/script ─────────────────────────────────────▶ Flask API ──▶ stderr ─▶ logs/backend.log
                                                         │                         │ (Alloy tails)
                                  one transaction        ▼                         ▼
                     ┌──────────────────────────────  PostgreSQL               Loki ─▶ Grafana
                     │  orders, reservations, stock,    ▲  ▲
                     │  packages, shipping_attempts     │  │ claims PENDING rows
                     │  + outbox_messages (same tx)     │  │ (FOR UPDATE SKIP LOCKED)
                     │                                  │  │
 Valkey ◀── cache ───┘                          marks   │  │
 (order summary, 30 s TTL,                   PUBLISHED  │  │
  invalidated by writes)                                │  │
                                                   outbox relay ──publish──▶ RabbitMQ
                                                                                │ orders.projection
                                                                                ▼
                                                  inbox row + DynamoDB  ◀── projection consumer
                                                  (idempotent, stage only moves forward)
```

PostgreSQL is the only source of truth. Valkey and DynamoDB can vanish without losing a
fact; RabbitMQ only moves messages that PostgreSQL has already recorded.

## The ten phases

| # | Phase | What you see | Concept |
| --- | --- | --- | --- |
| 1 | Receive stock | One `inventory_balances` row (SQL: there is no receive API) | on hand vs available |
| 2 | `createOrder` | Order `CREATED`, stock untouched, outbox empty | an order is intent, not a reservation |
| 3 | `allocateInventory` | `allocated` up, a reservation row, a `PENDING` outbox row, no DynamoDB item | allocation, transactional outbox |
| 4 | Relay + projection | Outbox `PUBLISHED`, queue counters, DynamoDB stage 1 | at-least-once delivery, read model |
| 5 | Order summary twice | Valkey entry appears; `keyspace_hits` +1 | cache-aside, TTL |
| 6 | `startPicking` | Cache entry gone, DynamoDB still stage 1 | invalidation on write, a projection gap |
| 7 | `recordPick` + `completePicking` | `picked` equals reserved, `PickingCompleted` published, stage 2 | picking, cumulative targets |
| 8 | `addPackage` + `finishPacking` | `packages` row, stage 3 | packing invariants |
| 9 | `shipOrder` | `on_hand` and `allocated` drop, attempt `SHIPPED` with tracking, stage 4 | shipping attempt, fake carrier |
| 10 | A deliberate server error | The client sees a generic error; Loki has the line with your `request_id` | structured logs, correlation ids |

Some terms, briefly:

- **Allocation** reserves stock for an order: `allocated` goes up, `available` goes down, and
  one `order_reservations` row per line and bin records where the units will come from.
- **Outbox**: the event is written in the same database transaction as the state change, so
  "state changed" and "event will be published" cannot disagree. Publishing happens later.
- **Projection**: a denormalized copy for reading (DynamoDB, one item per order). It is
  rebuilt from events, so it is allowed to lag and to be thrown away.
- **Stage**: events carry no version, so the projection ranks them by lifecycle position
  (1 allocated ... 4 shipped) and only moves forward; a duplicate or stale event changes nothing.
- **Cache**: Valkey holds the order summary for 30 s. A write deletes the entry after it
  commits; the TTL bounds the damage if that deletion is ever lost.
- **Shipping attempt**: the intent to ship is committed before the carrier is called, so a
  timeout leaves an `UNKNOWN` attempt to reconcile instead of a lost or duplicated shipment.
- **Request id**: sent as `X-Request-Id`, bound to every log line of that request, echoed in the
  response. It is how a user-visible failure becomes a findable log line.

## Reading the output yourself

After a `--keep-data` run you can look at the same evidence by hand (replace `<run id>`):

```sh
docker compose -p warehouse-fulfillment-lab exec postgres psql -U lab -d warehouse_lab \
  -c "select * from inventory_balances where client_id = 'demo-<run id>'" \
  -c "select event_type, status from outbox_messages where client_id = 'demo-<run id>' order by created_at"
```

In Grafana, Explore, data source Loki: `{service="backend"} |= "demo-err-<run id>"`.

## Known limits (honest list)

- `createOrder` and `startPicking` publish no events, so the projection cannot show `CREATED`
  or `PICKING` (phase 6 shows it).
- The cache hit is proven with Valkey's server-wide `keyspace_hits` counter, so another client
  reading at the same moment would add noise. On an idle lab it is exact.
- The queue's cumulative publish counter in the RabbitMQ management API lags by seconds, so the
  demo reports the consumer's own inbox rows (`processed=`) next to the live queue depth.
- The demo is the happy path. The failure drills (carrier timeout, duplicate webhook, lost
  events, Valkey down, ...) are separate exercises: see [the failure drills](failure-drills.md).

## Questions and answers

Try each question before opening its answer.

### Phase 1: receive stock

**Q.** We receive 10 units of one SKU into one bin. What will `on_hand`, `allocated` and
`available` be, and which of them is stored in the table?

<details><summary>Answer</summary>

`on_hand = 10`, `allocated = 0`, `available = 10`. The table stores `on_hand`, `allocated`,
`picked` and `packed`; `available` is computed as `on_hand - allocated`. Storing a derived
number would give you two values that can disagree. The table also has check constraints
(`allocated <= on_hand`, `picked <= allocated`), so the database refuses an impossible state
even if application code has a bug.
</details>

### Phase 2: createOrder

**Q.** `createOrder` asks for 3 units. Afterwards, what is `available`? Is anything in the outbox?

<details><summary>Answer</summary>

`available` is still 10 and the outbox is empty. Creating an order records what the customer
wants; reserving stock is a separate business decision (`allocateInventory`) that can fail
or be retried on its own. `CreateOrder` publishes no event, which is also why the projection
never shows a `CREATED` order.
</details>

### Phase 3: allocateInventory

**Q.** After `allocateInventory`, what is `available`? Has anything reached RabbitMQ or
DynamoDB, and what is the status of the outbox row?

<details><summary>Answer</summary>

`allocated = 3`, `available = 7`, one reservation row for 3 units in `BIN-A1`, and one
`OrderAllocated` outbox row with status `PENDING`. DynamoDB has no item and RabbitMQ has
received nothing: the relay is not running yet. The stock change, the reservation, the order
status and the outbox row were committed in one PostgreSQL transaction, so there is no state
where stock is reserved but the event is lost, or the reverse. Two workers allocating the last
unit at the same time are serialized by the row lock on the balance (see [the allocation notes](study/transactional-allocation.md)).
</details>

### Phase 4: outbox relay, RabbitMQ, projection

**Q.** We start the relay. What will the outbox row's status become, and what will DynamoDB
hold for this order (and what stage)?

<details><summary>Answer</summary>

The row becomes `PUBLISHED` and DynamoDB holds an item with status `ALLOCATED`, stage 1,
after the consumer processed the message (`processed=1`, queue `ready=0`). The relay publishes
first and marks the row second: a crash between the two means the row is published again, so
delivery is at-least-once and the consumer must be idempotent (the inbox table records each
message id so a redelivery is a no-op, and the projection's "only move the stage forward"
condition absorbs a duplicate even if that inbox row were lost). DynamoDB is derived data: if it
were wiped, `order_projection_cli rebuild` replays the outbox.
</details>

### Phase 5: cache

**Q.** We read the order summary twice. Which store answers the second read, and how could
you tell?

<details><summary>Answer</summary>

Valkey. Before the first read the key is absent; after it, the key exists with a TTL of about
30 s; the second read increases the server's `keyspace_hits` by one and does not query
PostgreSQL. The cache is optional by design: if Valkey is down the read falls back to
PostgreSQL and the API stays correct, only slower.
</details>

### Phase 6: startPicking

**Q.** `startPicking` changes the order status. What happens to the cached entry, and will
DynamoDB show `PICKING`?

<details><summary>Answer</summary>

The cached entry is deleted (absent), and DynamoDB still says `ALLOCATED`, stage 1. Writes
that change the cached header are wrapped by an invalidating use case that deletes the key
after the transaction commits; the use cases themselves know nothing about the cache. The
projection stays at stage 1 because `StartPicking` publishes no event: a known gap, and a good
reminder that a read model only knows what events tell it.
</details>

### Phase 7: picking

**Q.** After picking is complete, do `on_hand`, `allocated` or `picked` change?

<details><summary>Answer</summary>

Only `picked` changes (0 to 3). Units that are picked are still in the building and still
reserved, so `on_hand` and `allocated` stay at 10 and 3. `recordPick` takes a cumulative
target ("3 picked"), not a delta ("+3"), so a retry after a lost response cannot count units
twice. `completePicking` is allowed only when every reservation is fully picked and writes
`PickingCompleted` (projection stage 2).
</details>

### Phase 8: packing

**Q.** What must be true about the packages before `finishPacking` is allowed, and does stock change?

<details><summary>Answer</summary>

The packages must exactly cover every picked reservation: no unit left out, none counted
twice, none that was not picked. Here one box holds 3 units. Stock does not change; packing
is physical bookkeeping about boxes (weight, dimensions, contents). `OrderPacked` goes to the
outbox (stage 3) and the projection learns the package count.
</details>

### Phase 9: shipping

**Q.** After `shipOrder`, what do `on_hand`, `allocated` and `picked` become? What if the
carrier had timed out instead?

<details><summary>Answer</summary>

`on_hand = 7`, `allocated = 0`, `picked = 0`, so `available = 7`: the 3 shipped units left the
building and the reservation is consumed. The shipping attempt is `SHIPPED` with a tracking
number from the fake carrier, and `OrderShipped` moves the projection to stage 4 with the
tracking number. The attempt row is committed before the carrier is called and no database
transaction is held across the call. If the carrier had timed out, the attempt would be
`UNKNOWN`; `reconcileShipment` asks the carrier by attempt id before ever creating a shipment
again, so a lost response never produces a second shipment.
</details>

### Phase 10: logs

**Q.** We trigger a deliberate server-side failure with our own `X-Request-Id`. What does the
client learn about the cause, and where do you find the details?

<details><summary>Answer</summary>

The client sees only `INTERNAL: Internal server error`, plus the request id header: internal
details (table names, SQL) are not information a caller should get. The details are in the
server's JSON log line at level `ERROR` with the same `request_id` and the exception text. That
line went to stderr, `logs/backend.log`, Alloy, Loki and is searchable in Grafana. The app
knows nothing about Loki; the shell redirect and Alloy are the whole pipeline. The demo
provokes the error with a second API process whose database schema is empty (the technique of
`scripts/smoke_observability.sh`), so the main API and the demo data are untouched.
</details>

## Interview prompts this demo prepares

1. Why is `available` computed, and what stops two allocations from taking the last unit?
2. What goes wrong if the event is published inside the business transaction instead of
   through an outbox? What if it is published after the commit without one?
3. The relay crashes after publishing, before marking the row. What does the system do next?
4. Why can DynamoDB be wiped without losing data, and who repairs it?
5. When can the cache serve a stale order status, and what bounds the staleness?
6. A carrier call times out after creating the shipment. Walk through `UNKNOWN`.
7. How would you find every log line of one failed request?
