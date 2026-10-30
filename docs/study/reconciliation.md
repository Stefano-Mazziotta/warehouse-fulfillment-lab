# Events plus reconciliation: repairing what a webhook lost

Study note for the `integrations` capability. The external system is a fake sales
channel (`InMemorySalesChannel`, `PostgresFakeSalesChannel`) and it is the source of
truth for channel orders. Nothing here uses a network, Flask or HTTP.

## The problem

A webhook is a hint that something changed, not a guarantee. It can be dropped, delayed,
duplicated, reordered, or processed while our database is down. If we only trust
events, one lost message leaves the warehouse missing an order forever and nobody knows.

```text
Channel: order c1 created --webhook lost--X   WMS never hears about c1
Reconciler (periodic): "what changed since my checkpoint?" -> c1 -> same ingest path
```

Events are the fast path. Reconciliation is the slow, authoritative safety net.

## One ingest path for both

Webhook and reconciler both call `ReceiveChannelEvent`:

1. **Persist, then process.** The raw event is written to `integration_events`
   (`RECEIVED`) in its own committed transaction. If processing then fails, the evidence
   remains and nothing is lost.
2. **Inbox.** `IdempotentConsumer` records `(channel-order-ingest, event_id)` in the same
   transaction as the effects. A duplicate event ID is a no-op. The inbox key is the event
   ID alone, so provider-chosen IDs are assumed globally unique; the IDs we derive for
   reconciliation percent-encode the tenant and order parts so `("a:b", "c")` and
   `("a", "b:c")` can never share one.
3. **`IngestChannelOrder`** maps the channel order to the existing `CreateOrder`
   (idempotent) and records the accepted channel version in `channel_order_versions`.

Two layers of dedupe, on purpose: the inbox catches the same event twice; the version
rule catches the same order arriving via a webhook AND via reconciliation (different
event IDs, same business fact).

## Ordering rule (versions, not arrival order)

The channel keeps a monotonic `version` per order. For a known order:

| Incoming vs accepted | Result |
|---|---|
| older version | `STALE_IGNORED`, state does not regress |
| same/newer version, same content | `ALREADY_KNOWN` (newer only advances the version) |
| same/newer version, different content | `CONFLICT`: event marked `FAILED`, nothing overwritten |

Why not "latest wins"? The warehouse may already be allocating the original order.
Amending it is a business operation, so the lab surfaces it instead of guessing.

## Cursor vs `updated_at`

Paging by `updated_at > last_seen` skips orders that share a timestamp at a page
boundary. The cursor is the keyset `(updated_at, id)`, unique and totally ordered,
so a page boundary never splits ties.

## Overlap window

Commits are not visible in timestamp order: a transaction stamped 12:00:00 may commit
at 12:00:07, after we checkpointed 12:00:05. Clocks also skew. A strict checkpoint would
miss it forever. So the first page of every run starts `overlap` BEFORE the checkpoint
and re-reads recent history. Cost: some orders are read twice, which idempotency makes
harmless. The overlap is a bet about how late things arrive, not a proof; an order
later than the window is still missed (see below).

## Checkpoint rules

- Stored per `(source, owner)` in `integration_checkpoints`.
- Advanced only after every order of the page was processed and committed. A crash
  before that re-reads the page. Never advance first: that turns a crash into a gap.
- Never moves backwards, even though the overlap re-reads older orders.
- A conflict is a terminal, reported outcome, so it does not block the checkpoint. A
  processing failure does: the run stops with `failed > 0` and the next run retries.

## Concurrent reconcilers

Each page runs in a transaction that does `SELECT ... FOR UPDATE` on the checkpoint
row. A second reconciler for the same owner waits, then reads the checkpoint the first
advanced. The test shows the wait with `pg_blocking_pids` in two variants: with a cold
checkpoint it is the uncommitted INSERT that blocks, with an existing row only the
`FOR UPDATE` does (removing it makes the warm test fail). The lock is held while polling
the channel, so a slow channel stalls rivals; the alternative is `SKIP LOCKED`/advisory
try-lock and simply skipping the run.

## What can still go wrong

- An order that appears with an `updated_at` older than checkpoint minus overlap.
- A channel that mutates content without bumping the version (reported as a conflict).
- Hard deletes and cancellations: polling "updated since" never sees a row that is gone.
  Real APIs expose tombstones or status changes; this lab models creation only.
- Reconciliation proves the channel and WMS agree on order creation, not on later state.
- No broker wiring yet: the ingest handler could be driven by `RabbitMqConsumerRunner`
  (a documented follow-up).
- `integration_events` and `channel_order_versions` have no retention or replay tool.

## Interview questions

1. Why is "the webhook was delivered" not proof that systems are in sync?
2. Why a `(updated_at, id)` cursor rather than `updated_at`?
3. What is the overlap window protecting against, and what does it cost?
4. Why advance the checkpoint after processing, not before?
5. A webhook and a reconciliation run deliver the same order at once. What prevents two
   orders, and which layer does it?
6. v2 arrives, then v1. What happens? What if v2 changes quantities after allocation?
7. Two reconcilers start together. What serializes them, and what is the downside?
8. How would you detect an order the channel deleted?
