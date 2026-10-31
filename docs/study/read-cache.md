# Read cache: cache-aside over PostgreSQL

## What cache-aside is

The application, not the cache, owns the logic. On a read it asks the cache first; on a
miss it reads PostgreSQL and then stores the answer for next time. On a change it deletes
the entry (it does not write the new value) and lets the next read repopulate it.

```text
GraphQL order(orderId)
  -> GetOrderSummary -> CachingOrderQueries --hit--> Valkey
                              | miss / error
                              v
                        PostgresOrderQueries  (authoritative)
```

Only `get_summary` (the order header: id, warehouse, status) is cached. Lists and the
batched lines/reservations/packages loaders go straight to PostgreSQL: any new or changed
order alters some page, so freshness would need fan-out invalidation the lab does not need.

## Why PostgreSQL stays authoritative

Allocation needs multi-row locking and one transaction (see `transactional-allocation.md`).
A cache has no locks, no transaction with the stock rows and can vanish at any moment, so
a decision based on it could oversell. The rule in code:

- Write use cases (`AllocateOrder`, `StartPicking`, ...) take a transaction, never the
  read port or the cache. `test_order_cache_architecture.py` fails if any write module
  imports the cache, and `test_allocation_never_consults_the_cache` poisons the cache with a
  `CANCELLED` entry and shows allocation ignores it.
- The only thing a mutation does with the cache is delete an entry afterwards
  (`InvalidatingUseCase`). Deleting is safe even if wrong; reading is not.

## Hexagonal placement

`OrderSummaryCache` is a `Protocol` in `orders/application`; `valkey` is imported only in
`orders/infrastructure/valkey_order_summary_cache.py`. `compose_services` is the one place
that picks the adapter, from `LAB_VALKEY_URL`. Unset means no cache at all.

## Stale reads

| Scenario | Stale for |
| --- | --- |
| Mutation commits, invalidation succeeds | not stale (next read reloads) |
| Reader loaded the old row, mutation commits and invalidates, then the reader writes its old value | up to the TTL (30 s) |
| Invalidation lost (Valkey down, another process mutated, such as the webhook worker) | up to the TTL |

Invalidation narrows the window but cannot close it: reading PostgreSQL and writing the
cache are two steps, not one atomic action. The TTL is the real guarantee, so choose it as
the staleness you can explain to a warehouse operator. A stale header is tolerable for a
dashboard read; it would not be for the decision to allocate, which is why that never uses it.

Trade-off considered: write-through (update the cache in the mutation) would shorten the
window but couples every write path to the cache and makes an outage a write-path problem.
Delete-after-commit keeps outages out of writes.

## Stampede

When a hot entry expires or is invalidated, many concurrent readers miss together and all
query PostgreSQL. Here the query is a single indexed row read, so the lab accepts it. Known
mitigations when it matters: single-flight per key in the process, a short lock key in the
cache, TTL jitter, or serving the stale value while one reader refreshes. Not implemented on
purpose (YAGNI); name them in an interview.

Missing orders are not cached (no negative caching): it could hide an order created a
moment later by another process.

## Outage behavior

- Short timeouts (200 ms connect and socket, no retry): a slow cache must cost less than the
  query it saves.
- Every cache failure becomes a miss. `CachingOrderQueries` catches `Exception` on purpose,
  so even a bug in serialization degrades to PostgreSQL instead of an API error.
- Cooldown: after one failure the cache is skipped for 5 s, so a dead Valkey costs one
  timeout per window rather than one per request. After the window one request probes it.
- Invalidation errors are swallowed and never fail a committed mutation; the TTL covers them.
- An unreadable payload is a miss and gets overwritten.

Proofs: a fake cache raising `CacheUnavailable`, `TimeoutError` and `RuntimeError`; an
unreachable URL (connection refused); a socket that accepts but never answers (timeout);
and the real Compose service stopped (`docker compose -p warehouse-fulfillment-lab stop
valkey`, then the API tests with `LAB_TEST_VALKEY_DOWN_URL`).

## Running it

```text
docker compose -p warehouse-fulfillment-lab up -d valkey      # 127.0.0.1:56379
LAB_TEST_VALKEY_URL=valkey://127.0.0.1:56379/0 uv run pytest -q
LAB_VALKEY_URL=valkey://127.0.0.1:56379/0 ...                 # enable it in the app
```

## Questions to answer before an interview

1. Why delete on write instead of updating the cached value?
2. Which race still serves a stale header after invalidation, and what bounds it?
3. Why can the cache never take part in the allocation decision?
4. What would you change if the order page became the hottest query?
