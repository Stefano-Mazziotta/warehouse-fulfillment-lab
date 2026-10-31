# Mock interview checklist

A self-assessment for senior backend interviews, tied to what this lab actually built. It
follows the "Final Success Criteria" in `AGENTS.md`: Domain, Backend, Architecture,
Integrations, System Design.

It is **prediction first**. For every row: cover the right-hand columns, answer out loud in two
minutes, then check your answer against "A strong answer must include" and the evidence. The
bullets are a checklist of ideas, not a script. Rate yourself honestly; the goal is to find
what you cannot yet explain, not to score well.

Rating key: **N** not ready (I cannot explain it) / **S** shaky (I get the idea, miss failure
modes or trade-offs) / **G** solid (I can defend it under follow-up questions). Replace the
empty boxes with an `x` as you go.

Related: [demo](demo.md), [failure drills](failure-drills.md), [AWS map](aws-map.md),
[domain glossary](domain-glossary.md), [study notes](study/messaging.md).

## How to use this with "Interview mode"

1. Say `Interview mode` to the assistant in this repository. Per `AGENTS.md` it plays a senior
   backend interviewer and asks **one question at a time**.
2. Tell it which section to draw from (for example "Backend, concurrency only") or let it pick
   from your lowest ratings.
3. After each answer it should: evaluate your reasoning, name the missing considerations, ask
   one follow-up, and give concise feedback. It should not turn into a tutorial unless you ask.
4. Answer from memory first. Open the evidence column only afterwards.
5. Re-rate the row. Anything still N or S goes on the next session's list.

## 1. Domain

| # | Criterion | An interviewer asks | A strong answer must include | Evidence in this repo | N | S | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | What a WMS does | "What is a warehouse management system and what does it own?" | stock by location, owner, state (on hand, allocated, available); directs work (allocate, pick, pack, ship); not the storefront, not the carrier; it is the system of record for physical-world state | [glossary](domain-glossary.md), [domain rules](domain-rules.md), `docs/study/inventory-allocation.md` | [ ] | [ ] | [ ] |
| D2 | How an order moves through fulfillment | "Walk me through an order from `CREATED` to `SHIPPED`." | business operations not `updateStatus`; legal transitions; cancel allowed only before picking; partial picks; several packages; what each step changes in stock | [demo](demo.md) phases 2 to 9, `src/orders/domain/order.py`, `src/orders/domain/order_status.py` | [ ] | [ ] | [ ] |
| D3 | How inventory allocation works | "Two orders want the last unit. What decides who wins?" | `available = on_hand - allocated` is computed; all-or-nothing per order; one warehouse per order; deterministic lock order; allocation reserves, it does not move stock | `docs/study/order-allocation.md`, `docs/study/transactional-allocation.md`, Drill 1, `src/orders/application/allocate_order.py` | [ ] | [ ] | [ ] |
| D4 | How picking works | "A picker finds 3 of 5 units. What does the system do?" | partial pick is normal; cumulative target per reservation makes retries safe; picking does not change on hand; complete only when every line is fully picked; cancellation cutoff | `docs/study/picking.md`, [demo](demo.md) phase 7, `src/picking/application/record_pick.py` | [ ] | [ ] | [ ] |
| D5 | How packing works | "What makes a packing configuration valid?" | packages own contents, not a balance counter; per-reservation and per-line totals must equal what was picked; positive measurements; one reservation may split across packages; order guards state | `docs/study/packing.md`, `src/packing/domain/packing_config.py`, `src/packing/application/finish_packing.py` | [ ] | [ ] | [ ] |
| D6 | How shipping works | "The carrier call timed out. Did the shipment happen?" | persist attempt before the call; no DB transaction across the call; timeout means `UNKNOWN`, not failed; look up by attempt id before creating; finalize stock once; carrier idempotency is a contract to verify, not assume | `docs/study/shipping.md`, Drill 2, `src/shipping/application/ship_order.py`, `src/shipping/application/reconcile_shipment.py` | [ ] | [ ] | [ ] |
| D7 | What a 3PL is | "How does a 3PL differ from a retailer's own warehouse?" | inventory owned by the client, held by the 3PL; client isolation on every query; one 3PL, many clients and warehouses; billing is per client; the lab models owner as part of the stock key | [glossary: 3PL](domain-glossary.md), `docs/study/graphql-api.md` (tenant scoping) | [ ] | [ ] | [ ] |
| D8 | What EDI is | "What are 940, 945 and 856, and who sends each?" | brand to 3PL: 940 ship order; 3PL to brand: 945 shipping advice; 856 advance ship notice; control numbers; a 945 is a claim to reconcile, not proof | `docs/study/edi.md`, Drill 8, `src/integrations/edi/order_intake.py` | [ ] | [ ] | [ ] |

## 2. Backend

| # | Criterion | An interviewer asks | A strong answer must include | Evidence in this repo | N | S | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | Preventing overselling | "How do you guarantee you never sell stock you do not have?" | name the race (check then write); lock the stock rows in the same transaction as the write; re-read under lock; invariant `allocated <= on_hand` also as a DB constraint; what a cache or replica must never do | Drill 1, `docs/study/transactional-allocation.md`, `src/orders/infrastructure/postgres_order_transaction.py` | [ ] | [ ] | [ ] |
| B2 | Transactions | "Where does the transaction boundary go, and why?" | one transaction per business state change (order + stock + reservations + outbox row); never across a network call; domain decides, application orchestrates | `docs/decisions/order-transaction.md`, `src/orders/application/order_transaction.py` | [ ] | [ ] | [ ] |
| B3 | Row-level locking | "`SELECT ... FOR UPDATE`, optimistic locking, `SKIP LOCKED`: when each?" | pessimistic for hot contended stock rows; sorted lock order to avoid deadlocks; `SKIP LOCKED` for work queues (relay); optimistic/conditional writes where conflicts are rare (DynamoDB stage); isolation level effects | Drill 1, Drill 4, `src/messaging/application/outbox_relay.py`, `src/orders/infrastructure/dynamodb_order_projection.py` | [ ] | [ ] | [ ] |
| B4 | Asynchronous processing | "Why not publish to the broker inside the request?" | dual-write problem (commit then publish loses; publish then commit lies); outbox row in the same transaction; relay publishes; consumers are separate | `docs/study/messaging.md`, Drill 5, `src/messaging/application/event_recorder.py` | [ ] | [ ] | [ ] |
| B5 | Retries | "What can you safely retry, and what bounds the retries?" | only idempotent operations; bounded exponential backoff; dead after a limit; retry changes ordering; do not retry a poison message forever | `src/messaging/domain/retry_policy.py`, `src/messaging/application/outbox_relay.py`, Drill 5 | [ ] | [ ] | [ ] |
| B6 | Idempotency | "A webhook arrives twice. Where do you stop it?" | stable event id; unique key in the same transaction as the effect (inbox); same payload twice is a no-op, different payload under the same key is a conflict; idempotent mutations (`CreateOrder` compares payload) | Drill 3, Drill 8, `src/messaging/application/idempotent_consumer.py`, `src/orders/application/create_order.py` | [ ] | [ ] | [ ] |
| B7 | Reconciliation | "How do you know you did not miss an event?" | webhooks are hints; poll by `updated_at` with a keyset cursor; checkpoint advances only after durable processing; overlap window; same ingest path so the repair is idempotent | Drill 6, `docs/study/reconciliation.md`, `src/integrations/application/reconcile_channel_orders.py` | [ ] | [ ] | [ ] |

## 3. Architecture

| # | Criterion | An interviewer asks | A strong answer must include | Evidence in this repo | N | S | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | Why DDD is useful | "Where did you actually use DDD, and where did you refuse to?" | protect business rules (allocation, transitions, packing conservation) in the domain; no ceremony (no generic repositories everywhere); domain testable without Flask or SQL | `src/orders/domain/order.py`, `src/packing/domain/packing_config.py`, `tests/orders/test_order_architecture.py` | [ ] | [ ] | [ ] |
| A2 | Aggregate boundaries | "What is your aggregate, and why not bigger or smaller?" | order locks as the consistency boundary for lines, reservations, packages; stock is a separate resource locked in a fixed order; what happens across the boundary (outbox, eventual) | `docs/decisions/order-transaction.md`, `src/orders/domain/reservation.py` | [ ] | [ ] | [ ] |
| A3 | Why Hexagonal | "Show me where a dependency points the wrong way, if any." | domain and application import no Flask, SQLAlchemy, pika or boto3; ports in application, adapters in infrastructure; architecture tests enforce it; honest exceptions (events vocabulary coupling) | `tests/api/test_api_architecture.py`, `tests/messaging/test_messaging_architecture.py`, `src/shipping/application/carrier_port.py` | [ ] | [ ] | [ ] |
| A4 | Why vertical slicing | "Why folders by capability and not controllers/services/models?" | change one business capability in one place; boundaries match the language of the business; cost: shared vocabulary and metadata coupling need discipline | `src/` capability folders (orders, picking, packing, shipping, messaging, integrations) | [ ] | [ ] | [ ] |
| A5 | Why screaming architecture | "What does your repository tell a newcomer?" | top level names the business, not the framework; filenames match class names; the framework is a detail at the edge | [README](../README.md), `src/` | [ ] | [ ] | [ ] |
| A6 | Where ports and adapters belong | "Where does the carrier abstraction live and who implements it?" | the use case owns the port (`CarrierPort`); UPS/FedEx-style details live in adapters; the fake carrier is an adapter that honors an idempotency contract; fakes make failure injectable | `src/shipping/application/carrier_port.py`, `src/shipping/infrastructure/postgres_fake_carrier.py`, `src/integrations/application/sales_channel_port.py` | [ ] | [ ] | [ ] |

## 4. Integrations

| # | Criterion | An interviewer asks | A strong answer must include | Evidence in this repo | N | S | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I1 | REST vs GraphQL | "Why GraphQL here, and why still some REST?" | GraphQL for business capabilities and nested reads (DataLoader, pagination, limits); REST only for inbound webhooks and health; thin resolvers over use cases; costs (N+1, query complexity, authorization, rate limiting) | `docs/study/graphql-api.md`, `docs/api/schema.graphql`, `src/api/app_factory.py` | [ ] | [ ] | [ ] |
| I2 | Webhooks | "Design a webhook receiver. What is lightweight, what is not?" | validate, persist raw event, enqueue or process idempotently; at-least-once; event ids and unique constraints; out-of-order; never assume delivery means in sync | Drill 3, `src/integrations/application/receive_channel_event.py` | [ ] | [ ] | [ ] |
| I3 | Queues | "Which delivery guarantee do you have and what must the consumer do?" | at-least-once, ordering not guaranteed; ack only after commit; inbox dedup; retry queue, DLQ, and the missing replay tool; broker is not exactly-once business execution | `docs/study/messaging.md`, Drill 5, Drill 4, `src/messaging/application/idempotent_consumer.py` | [ ] | [ ] | [ ] |
| I4 | EDI | "A partner resends the order with a changed quantity. What happens?" | control number as inbox key; same payload is a duplicate, changed payload under the same business key is a conflict, never silently overwritten; acknowledgements as claims to reconcile | Drill 8, `docs/study/edi.md`, `src/integrations/edi/order_intake.py` | [ ] | [ ] | [ ] |
| I5 | Carrier integrations | "How do you integrate a carrier you cannot trust?" | abstraction at the use case boundary; attempt persisted first; `UNKNOWN` outcome; reconcile by lookup; adapters absorb carrier quirks; label and tracking are results, not assumptions | Drill 2, `docs/study/shipping.md` | [ ] | [ ] | [ ] |
| I6 | External system failures | "What do you do when the cache, broker or database dependency fails?" | classify by authority: cache down is a miss; broker down means outbox keeps accumulating; DB down means refuse writes; DynamoDB is rebuildable; what the operator sees in logs | Drill 7, [demo](demo.md) phases 4 and 5, `docs/study/read-cache.md`, `docs/study/observability.md` | [ ] | [ ] | [ ] |

## 5. System design

| # | Criterion | An interviewer asks | A strong answer must include | Evidence in this repo | N | S | G |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | The end-to-end flow | "Design order flow from a sales channel to a delivered parcel." | the chain below, with consistency, transaction, failure and integration boundaries called out at each hop | [demo](demo.md), [AWS map diagram](aws-map.md#the-whole-flow-with-aws-placement-and-failure-boundaries) | [ ] | [ ] | [ ] |
| S2 | Consistency and transaction boundaries | "What is atomic and what is eventual?" | atomic: order + stock + reservation + outbox row; eventual: broker, projection, cache, channel updates; PostgreSQL is the only source of truth | `docs/decisions/order-transaction.md`, `docs/study/order-projection.md` | [ ] | [ ] | [ ] |
| S3 | Scaling and managed services | "How would this run on AWS and what would break first?" | RDS failover and connection limits; reads from replicas vs authoritative reads; queue semantics change; hot partitions; compute choice for long-running consumers | [AWS map](aws-map.md) | [ ] | [ ] | [ ] |
| S4 | Observability | "A customer says an order is stuck. How do you find out why?" | request id and event id in structured logs; outbox status; DLQ depth; reconcile; honest gaps (no metrics, traces) | [demo](demo.md) phase 10, `docs/study/observability.md` | [ ] | [ ] | [ ] |

### Say it in 2 minutes

Set a timer. Without notes, explain the whole flow aloud, then check what you skipped.

```text
Sales Channel -> Integration -> Order -> Allocation -> Picking -> Packing
              -> Shipping -> Carrier -> Tracking -> Sales Channel
```

Your two minutes must cover, in this order:

1. How an order enters (webhook plus polling) and why both.
2. The one transaction that allocates stock, and what it locks.
3. How the rest of the world hears about it without a dual write.
4. Picking and packing as quantity conservation.
5. The shipping call: what is committed before it, what `UNKNOWN` means.
6. Tracking back to the channel, and what repairs a lost update.
7. Two named failure modes and one thing you did not build.

Self-rating: [ ] N  [ ] S  [ ] G

## Challenge me

Scenarios from `AGENTS.md`. For each one, predict the outcome first. "Runnable" means the lab
has an exercise you can run; "not built" means the lab does not model it, so say that plainly
instead of improvising an answer.

| Scenario | Runnable drill? | Where to look | N | S | G |
| --- | --- | --- | --- | --- | --- |
| Two workers allocate the same SKU | Yes: Drill 1 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| A carrier times out after creating a shipment | Yes: Drill 2 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| A webhook is delivered twice | Yes: Drill 3 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| Events arrive out of order | Yes: Drill 4 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| A worker crashes halfway through an operation | Yes: Drill 5 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| The external system never receives our update / a webhook is lost | Yes: Drill 6 (inbound direction) | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| The cache dies | Yes: Drill 7 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| An EDI document arrives twice | Yes: Drill 8 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| A shipment succeeds but the response is lost | Covered by Drill 2 | [failure drills](failure-drills.md) | [ ] | [ ] | [ ] |
| Physical inventory differs from database inventory | **Not built** (no cycle counts or adjustments) | discuss: cycle counts, adjustment movements with reason codes, who may adjust | [ ] | [ ] | [ ] |
| One package ships while another fails | **Not built** (shipping attempt is atomic per order) | discuss: per-package shipments, partial fulfillment, split stock decrement | [ ] | [ ] | [ ] |
| Two warehouses try to fulfill the same order | **Not built** (one warehouse per order by design) | discuss: order splitting, source-of-truth for the assignment, locks across warehouses | [ ] | [ ] | [ ] |

Note: Drill 6 repairs a lost *inbound* channel event. The *outbound* direction (we update the
channel and it never arrives) is not built; say so and describe the same pattern mirrored.

## Honest known gaps, and how to talk about them

Pulled from the tracker closures. In an interview a gap you can name and reason about reads as
seniority; a gap you hide and get asked about reads as bluffing. Format: **what is missing,
what could go wrong, what you would do, what the lab did instead.**

| Gap | Say it like this | Rated |
| --- | --- | --- |
| No authentication; `X-Client-Id` is a stand-in | "The tenant header is trusted. It proves scoping and isolation logic, not identity. In production it comes from a verified token and the scope is applied server side." | [ ] N [ ] S [ ] G |
| EDI tenant comes from the unauthenticated ISA06 sender id | "A sender can claim to be anyone. Real transports authenticate the partner (AS2 certificates, SFTP keys) before parsing, and sender-to-tenant mapping is configuration." | [ ] N [ ] S [ ] G |
| No webhook signature verification | "Anyone who can reach the endpoint can post events. I would verify an HMAC or signature over the raw body with a shared secret and reject replays by timestamp." | [ ] N [ ] S [ ] G |
| No rate limiting | "GraphQL has depth and complexity limits, but no per-client throttle. I would add it at the gateway and keep limits per tenant." | [ ] N [ ] S [ ] G |
| No DLQ replay tool | "Dead messages are kept and visible, but nothing re-drives them. I would add a reviewed, idempotent replay that records who replayed what." | [ ] N [ ] S [ ] G |
| Locks held during I/O (relay claim while publishing; checkpoint row lock while polling the channel) | "It is simple and safe, but a slow broker or channel holds a lock and reduces concurrency. Alternatives: lease columns with expiry, or claim then publish outside the lock and accept duplicates." | [ ] N [ ] S [ ] G |
| No production relay entry point | "The demo and drills use a client-scoped relay worker. A real service needs a supervised relay process." | [ ] N [ ] S [ ] G |
| `createOrder` and `startPicking` emit no events | "So the projection cannot show CREATED or PICKING. It is a missing event vocabulary, not a design flaw I would defend." | [ ] N [ ] S [ ] G |
| Ordering is best-effort; retry reorders by design | "Correctness does not depend on order: the projection uses lifecycle stage as a version and ignores stale events." | [ ] N [ ] S [ ] G |
| No stampede protection on the cache; invalidation has no cooldown while Valkey is down | "A hot key expiring can send many readers to the database. I would add request coalescing or jittered TTL." | [ ] N [ ] S [ ] G |
| Outbox and inbox have no retention; dead outbox rows are not logged | "They grow without bound. I would add a purge job and an alert on `DEAD` rows." | [ ] N [ ] S [ ] G |
| No metrics, traces, log rotation or retention; no exception-text scrubbing | "Logs answer 'what happened to this request'. They do not give SLOs. I would add RED metrics and traces, and scrub secrets before logs leave the process." | [ ] N [ ] S [ ] G |
| Carrier, sales channel and EDI sender are lab fakes | "They prove my side of the contract (what I persist, how I retry). They are not evidence about any real carrier's idempotency." | [ ] N [ ] S [ ] G |
| Unroutable events retry then go `DEAD`; broker blackhole timeout untested | "A hung broker connection could stall the relay; I would set publish timeouts and test them." | [ ] N [ ] S [ ] G |
| Not modeled: drift, per-package shipment failure, multi-warehouse orders, returns, backorders | "Out of scope on purpose. I can describe the design, but I have not proven it." | [ ] N [ ] S [ ] G |

Rules for talking about gaps:

- Say what the lab *does* prove before what it does not.
- Never claim a property you did not test. If a test was written after the code or a mutation
  check was not run, that is part of the honest answer.
- Do not describe any vendor's private architecture. Say "industry convention" or "my design".
- If asked about a managed service, tag what you verified against the docs versus what you are
  reasoning from experience ([AWS map](aws-map.md#how-to-read-the-claims)).

## After a session

1. Write down every question you could not answer on the first try.
2. Pick the lowest-rated row and re-read its evidence column.
3. Re-run the matching drill (`scripts/drills/run_drill.sh <n>`) or the demo phase.
4. If an answer produced a real design decision, record it under `docs/decisions/` using the
   format in `AGENTS.md`.
