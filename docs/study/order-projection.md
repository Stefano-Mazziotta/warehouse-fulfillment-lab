# Order projection: a rebuildable read model in DynamoDB Local

## What a projection is

A projection (read model) is a second copy of some facts, shaped for one way of reading
them and fed from events. It is derived data: if it is lost, you recompute it from the
source. It is not a cache (a cache is filled lazily on a miss and expires) and not a
replica (it has a different shape and only the facts the events carry).

```text
PostgreSQL (authoritative)
  order change + outbox row, ONE transaction
        |
   OutboxRelay --> RabbitMQ exchange fulfillment.events
                      |  routing keys: the 5 order events
                      v
              queue orders.projection  (own retry queue + DLQ)
                      |
   IdempotentConsumer (PG inbox) -> ProjectOrderEvent -> OrderProjection port
                                                              |
                                                     DynamoDB Local table
```

The relay is not involved: it stays generic and never waits for DynamoDB. The projection
is just one more consumer with its own queue, so a slow or dead DynamoDB retries and
dead-letters on `orders.projection` only (see `messaging.md` for ack-after-commit, retry
and DLQ).

## Why DynamoDB here, and why not as the source of truth

DynamoDB answers key-shaped questions at flat latency: "this order" and "all orders of
this owner". That is exactly this read model:

| Item | Value |
| --- | --- |
| PK | `OWNER#<client_id>` |
| SK | `ORDER#<order_id>` |
| attributes | `order_id`, `status`, `stage`, `warehouse_id`, `line_count`, `package_count`, `tracking_number`, `last_event_id` |

`GetItem` for one order, `Query` on the PK for an owner's orders (sorted by SK). No scans.
The owner leads the key, so a query cannot cross owners.

It must not be the source of truth. Allocation needs to lock several stock rows in a fixed
order and commit them atomically with the order and the outbox row (see
`transactional-allocation.md`). DynamoDB has no `SELECT ... FOR UPDATE` (its
transactions are optimistic and bounded) and cannot join the PostgreSQL transaction. Nothing that allocates, picks, packs or ships reads this
table; the projection "can never authorize anything". A dashboard may show a stale status,
a decision may not rely on it.

Local only: DynamoDB Local (`amazon/dynamodb-local`, in-memory, `127.0.0.1:58000`, dummy
credentials, endpoint from `LAB_DYNAMODB_URL`). The AWS equivalents (on-demand table,
IAM role instead of dummy keys) are an adapter-configuration change, not a design change.

## What the events allow

The read model contains an order summary, its status and its package count, because the
published events carry exactly that:

| Event | Contributes |
| --- | --- |
| `OrderAllocated` | status ALLOCATED, warehouse, line count |
| `PickingCompleted` | status PICKED |
| `OrderPacked` | status PACKED, package count |
| `OrderShipped` | status SHIPPED, package count, tracking number |
| `OrderCancelled` | status CANCELLED |

Gaps worth naming: `CreateOrder` and `StartPicking` publish nothing, so CREATED and
PICKING are invisible here (an order appears at allocation). Adding events would be a
change to the published language, not to the projection.

## Idempotency and ordering

The events have no version or sequence number. What they have: each fact happens at most
once per order and the lifecycle only moves forward. So the position in the lifecycle is
the version (`stage`: ALLOCATED 1, PICKED 2, PACKED 3, SHIPPED 4, CANCELLED 5). Cancel is
only possible before picking, so it never races stages 2 to 4; it ranks last because it is
terminal. This avoids changing outbox semantics.

`apply` is two writes, both safe to repeat:

1. Facts (warehouse, counts, tracking) are `SET` unconditionally. They never change once
   known, so a late event may still contribute them. An `OrderAllocated` that arrives after
   `OrderPacked` still fills in the warehouse.
2. Status and stage are `SET` under `attribute_not_exists(stage) OR stage < :stage`. A
   duplicate (equal stage) or stale event (lower stage) fails the condition and changes
   nothing. The condition runs inside DynamoDB, so two consumers cannot interleave a
   read-then-write and regress the status.

Two layers of idempotency, on purpose:

- The PostgreSQL inbox drops a redelivered `message_id` before it reaches DynamoDB. The
  handler and the inbox row commit together; if DynamoDB fails the inbox row rolls back and
  the redelivery is processed.
- The conditional write makes the projection idempotent on its own. That is what lets the
  rebuild replay without an inbox, and makes a lost inbox harmless.

A crash between the two writes leaves an item with facts but no stage. `get` reports such
an item as absent until the redelivery lands the status.

Proofs: all 24 arrival orders of the four lifecycle events converge, and after every prefix
the status equals the furthest stage seen; the same assertions run against the in-memory
double and real DynamoDB Local (one contract file for both).

## Rebuild

`RebuildOrderProjection` resets the table and replays every `order` row of
`outbox_messages` oldest first, whatever its delivery status (a committed event is a fact
even if the relay has not published it, or gave up). It uses the same `ProjectOrderEvent`.
The PostgreSQL connection is opened read-only (`transaction_read_only = on`), and a test
compares the outbox before and after.

```text
docker compose -p warehouse-fulfillment-lab up -d dynamodb-local rabbitmq
export LAB_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab
export LAB_DYNAMODB_URL=http://127.0.0.1:58000
export LAB_AMQP_URL=amqp://lab:lab@127.0.0.1:55672/
uv run python -m orders.infrastructure.order_projection_cli run       # feed it
uv run python -m orders.infrastructure.order_projection_cli rebuild   # wipe and replay
```

Observed: restarting the in-memory container drops the table; consumers then fail with
`ResourceNotFoundException`, retry and dead-letter, and `rebuild` brings everything back.
Events in the DLQ are not lost, but there is no replay tool yet; after a long outage a
rebuild is the simpler repair.

Replaying while the live consumer runs is safe (conditional writes absorb the overlap)
except for the instant of the wipe, when readers see an empty projection.

Limits: the whole outbox is the history. There is no retention yet, so a rebuild grows with
it; production systems snapshot or compact. Rebuild is an operator action, not part of any
request.

## Trade-offs: consumer-fed versus relay-fed

| | Consumer on its own queue (chosen) | Relay writes DynamoDB directly |
| --- | --- | --- |
| DynamoDB slow or down | only `orders.projection` retries and dead-letters | holds the relay's row locks, delays every event |
| Adding another projection | one more queue | grows the relay |
| Dedup, retry, DLQ | reused (inbox, retry queue, DLQ) | reinvented |
| Moving parts | broker in the path | fewer |
| Freshness | broker hop plus retries | immediate |

Also considered: updating DynamoDB inside the order transaction. That is a dual write; it
fails the same way "publish then commit" does in `messaging.md`.

## Questions to answer before an interview

1. Events have no version. What did we use instead, and what would break it?
2. Why are facts written unconditionally but the status conditionally?
3. Why can the projection never authorize an allocation, even if it is "almost always" right?
4. A projection is lost. What exactly do you replay, and why is that complete?
5. What would you change to make a rebuild cheap with a billion events?
