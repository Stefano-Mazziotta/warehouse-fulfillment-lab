# GraphQL API over the fulfillment use cases

## What the adapter does

`src/api/` is the only package that imports Flask or Strawberry. A mutation parses its
input into a command, calls exactly one use case and wraps the result in a payload type.
Nothing in a resolver knows SQL or a transaction. Dependencies point inward:

```text
Flask view -> resolver -> application use case -> domain
                              |
                              +-> read-side port <- Postgres query adapter
```

`create_app(config, engine=None, services=None)` is the composition root. Services are
passed into the view, never stored on `flask.g` or looked up globally. The `engine` and
`services` parameters exist so tests can inject a disposable schema or a failing use case.

## REST versus GraphQL boundary

GraphQL exposes business capabilities (`createOrder`, `allocateInventory`, `startPicking`,
`recordPick`, `completePicking`, `addPackage`, `finishPacking`, `shipOrder`,
`reconcileShipment`). REST exists only where GraphQL is the wrong shape: a liveness probe
(`GET /health`) and an inbound webhook from a system that dictates its own HTTP contract
(`POST /webhooks/sales-channel`). The webhook validates, persists the raw event, processes it
through the idempotent inbox and returns 202 for new and duplicate event IDs alike; a bad
payload is a 400. The full request/response contract and retry policy live in
`docs/api/sales-channel-webhook.md`.

## Idempotent mutations

Each mutation inherits its use case's retry contract: identical `createOrder` and
`addPackage` return the stored result, `allocateInventory`, `startPicking`,
`completePicking`, `finishPacking` and `cancelOrder` are no-ops when already done,
`recordPick` takes a cumulative target (not a delta) and `shipOrder` reuses its single
attempt. Retrying after a lost response is therefore safe without operation IDs.

## Errors in one place

`error_codes.py` is the only mapping table and `ErrorMapping` applies it after execution.
`OrderNotFound` and `InventoryNotFound` become `NOT_FOUND`; `OrderError`, `ShippingError`
and `InventoryError` raised by a use case become `CONFLICT`. The same exceptions raised
while building a command from the input (blank id, zero quantity) are converted at the edge
into `BAD_USER_INPUT`, because the client could have avoided them. Anything else is
`INTERNAL` with a fixed message and no stack trace; Strawberry logs the original server-side.

## N+1 and DataLoader

`orders(first: 20)` returns headers only. `lines`, `reservations`, `packages` and
`shipment` are resolved through one `DataLoader` each, created per request and scoped to
the caller. All orders in the page ask during the same event-loop tick, so the loader issues
one batched `WHERE order_id IN (...)` query per collection.

| Page of 20 orders, nested lines + reservations + packages + shipment | Statements |
| --- | --- |
| With DataLoader, 3 orders | 7 |
| With DataLoader, 20 orders | 7 |
| Mutation check: batch size forced to 1, 3 orders | 19 |
| Mutation check: batch size forced to 1, 20 orders | 121 |

The 7 are: page, lines, reservations, packages and package items, attempts and attempt
packages. `test_graphql_n_plus_one.py` counts statements with SQLAlchemy's
`before_cursor_execute` event and also proves the counter can see an O(n) pattern.

Strawberry's DataLoader is asyncio-based, so the Flask view is the async one and the
blocking SQLAlchemy calls run on the request's event loop. Each request has its own loop,
so this costs nothing at lab scale; a high-concurrency server would offload them to threads.

## Cursor pagination versus offset

Orders are ordered by `order_id` and the cursor is the last returned id: `WHERE order_id >
:cursor ORDER BY order_id LIMIT n+1`. The extra row answers `hasNextPage` without a COUNT.
Offset paging skips `OFFSET` rows on every request and repeats or drops rows when something
is inserted before the offset; the keyset query uses the primary key index and a new order
sorting before the cursor does not shift later pages. The cursor is base64 of a prefixed id,
opaque to clients; a malformed one is `BAD_USER_INPUT`. Trade-off: the sort key is fixed to
the order id, which is stable but not chronological.

## Depth and complexity limits

Both are graphql-core validation rules, so a rejected query runs no resolver.

- Depth: at most 7 levels, introspection included (`__schema { types { fields { type
  { ofType ... } } } }` is a classic abuse). Code `QUERY_TOO_DEEP`.
- Cost: every field costs 1 and a field with `first` multiplies its subtree by that page
  size, read from the request variables. Limit 1000. The same nested page costs 701 with
  `first: 20` and 1751 with `first: 50`, so the second is rejected with `QUERY_TOO_COMPLEX`.
  Aliases and fragments count; a fragment cycle cannot hang the rule.
- `first` is capped at 50 (default 20) and violations are `BAD_USER_INPUT`.

Not done: per-client rate limiting (needs shared state to be meaningful across workers),
persisted queries and timeouts.

## Why X-Client-Id is only a stand-in

There is no authentication system in this lab. The header lets every use case be keyed by
owner so isolation can be proven: another client gets `NOT_FOUND` for reads and writes, and
cannot even see that the order exists. But anyone can send any header. Real authentication
would verify a credential (signed token, mTLS) at the edge and derive `client_id` from it;
the rest of the code would not change because it only ever sees the context's `client_id`.
The webhook has the equivalent gap: it should verify the sender's signature.

## Interview questions

1. Why return `NOT_FOUND` rather than `FORBIDDEN` for someone else's order?
2. How do you stop `orders { lines { ... } }` from issuing one query per order? What if the
   field resolvers were synchronous?
3. When is a domain exception a conflict and when is it bad input? Where did we decide?
4. Why is `recordPick` a cumulative target, and how does that make the mutation retry safe?
5. What breaks with offset pagination under concurrent inserts, and what does keyset cost you?
6. A client sends `first: 50` with deep nesting. Depth is fine; why can it still hurt, and
   how is the cost estimated when `first` is a variable?
7. The webhook answers 202 for a duplicate event id. What would a 409 do to the sender?
8. What would you add before exposing this API publicly?
