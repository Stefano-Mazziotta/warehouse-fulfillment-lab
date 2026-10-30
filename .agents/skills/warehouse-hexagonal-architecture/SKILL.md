---
name: warehouse-hexagonal-architecture
description: Design, explain, review, and refactor Python ports and adapters in warehouse-fulfillment-lab using domain-first vertical slices and thin Flask/GraphQL adapters. Use for inventory, order, picking, packing, shipping, messaging, or integration changes involving dependency direction, Protocol ports, transactions, idempotency, or infrastructure coupling. Preserve the mentor-first learning workflow; do not use for unrelated projects or cosmetic edits.
---

# Warehouse Hexagonal Architecture

## Establish scope

1. Read the repository's `AGENTS.md` and instructions governing the touched files.
2. Inspect the checkout, target branch, relevant tests, and task/decision records.
   For a stacked PR, compare its head with its own base; do not report inherited
   changes as new findings.
3. Read [the project map](references/project-map.md). Verify its paths against the
   checkout: `master` may contain only the inventory skeleton while a feature
   branch contains the extended lab. Do not assume proposed features are merged.
4. Identify the requested mode:
   - **Learning/design:** ask for the learner's approach, then give progressive
     hints. Provide a complete exercise implementation only when explicitly asked.
   - **Review:** inspect and explain defects/trade-offs; do not rewrite code.
   - **Explicit implementation/refactor:** change only the authorized slice,
     preserve behavior, and verify the affected boundaries.
5. Follow the task's authorization. A review does not authorize publishing
   comments, changing files, approving, or merging. Publish only when asked;
   treat a PR request as authorization to create that PR, not to merge it.

## Protect business boundaries

Start with the warehouse operation, actor, inputs, result, valid transitions,
invariants, and consistency boundary. Prefer names such as `AllocateOrder`,
`RecordPick`, and `ShipOrder` to generic status setters and CRUD services.

| Boundary | Responsibility | Allowed dependencies |
| --- | --- | --- |
| Domain | Identity, quantities, ownership, transitions, conservation | Standard library and justified domain types |
| Application | Use-case orchestration, transaction scope, ports, outcomes | Domain, application contracts, standard library |
| Inbound adapter | HTTP/GraphQL/CLI/message mapping and protocol errors | Application contracts, domain inputs, transport libraries |
| Outbound adapter | SQL, SDK calls, serialization, cache/broker behavior | Consumed ports, domain/application types, infrastructure libraries |
| Composition root | Construct adapters and inject dependencies | All required layers for wiring only |

Keep Flask, Strawberry/GraphQL, SQLAlchemy, psycopg, Pika, Valkey, boto3, and carrier
SDKs outside domain/application code. Map SQL rows, SDK results, and wire formats
in adapters. Do not pass `Request`, `Response`, `Info`, SQL connections, or broker
delivery objects into use cases.

Preserve capability-first packages and current naming. Do not create a global
`controllers/services/repositories` hierarchy or rename `adapters` merely to match
a diagram. Keep ports with the capability that consumes them. Allow justified
cross-capability application contracts/domain identities; reject cycles and
inner-layer imports of another capability's infrastructure.

## Use idiomatic Python contracts

- Use small `typing.Protocol` ports owned by the consuming application capability.
  Define only required operations. Let adapters satisfy them structurally without
  mandatory protocol inheritance.
- Treat a plain use-case class/function as an inbound contract when sufficient.
  Do not add an interface, command bus, DTO, factory, or repository per operation
  to imitate the upstream TypeScript layout.
- Inject dependencies through constructors/arguments. Reuse domain values,
  application dataclasses, `Callable` clocks/ID generators, and context managers.
  Keep transport DTOs at the edge; avoid redundant conversion layers.
- Preserve immutable snapshots where the domain uses frozen dataclasses. Validate
  identity components, exact integer quantities (including Python's `bool` trap),
  ownership, and transitions at the appropriate boundary.
- Separate business rejection, invalid transport input, and dependency failure.
  Translate technology exceptions at adapters without hiding programming errors
  or breaking rollback. Use ordinary Python logging unless a specific business
  or testing need justifies another abstraction.

## Inspect transactions and retries

Separate the local commit boundary from remote side effects. A port makes I/O
replaceable; it does not make SQL atomic with a carrier, broker, or projection.

Trace success, rejection, concurrent execution, duplicate delivery, and crashes
before/after each commit or remote call. Check the following where relevant:

- Scope stock by owner, SKU, warehouse, and location; scope orders by owner and
  order ID. Preserve complete reservation identities in picking and packing.
- Keep multi-line allocation, reservations, and the order transition in one
  transaction. Inspect consistent lock ordering and all-or-nothing failure in
  the database adapter; an in-memory fake cannot prove locking safety.
- Validate conservation of reserved, picked, and packaged quantities. Distinguish
  an aggregate stock count from proof that this order owns the reservation.
- Persist a stable shipping attempt before calling the carrier. Inspect recovery
  of unknown outcomes and receipt matching. Keep remote carrier waits outside
  database lock/transaction scopes.
- Encode composite idempotency keys unambiguously. Check duplicate IDs with
  changed payloads and ensure persisted evidence matches committed effects.
- Where outbox/inbox patterns exist, verify shared local transactions and
  acknowledgement after commit. Distinguish publisher confirms from consumer
  completion; inspect every retry/dead-letter hop before claiming no loss.
- Treat caches/projections as derived state. Explain tolerated staleness,
  invalidation, out-of-order events, replay, and rebuild limitations.

Apply only the rules relevant to the task and checkout. Do not implement missing
shipping, messaging, or cache features just to satisfy this checklist.

## Keep Flask at the edge

Use an application factory and explicit composition. Register blueprints/views
there; keep domain rules and concrete adapter creation out of routes. Support
injected dependencies in tests instead of global singletons or service lookup
through `flask.g`.

Map transport input into owner-scoped domain/application input, call a use case,
and map the outcome back to the protocol. Keep GraphQL error semantics separate
from REST status/envelope semantics; preserve HTTP status and headers.

For GraphQL, inspect pagination, bounded validation work, request-scoped batching,
and loader freshness after mutations. For webhooks/messages, inspect envelope
validation, durable acceptance, bounded retry metadata, and replay. Keep logs
useful without copying credentials, raw queries, or business payloads.

Respect documented local-lab authentication and fake-provider boundaries. Explain
risks if exposure changes, but do not introduce authentication or production
infrastructure without a concrete request. Do not apply REST URL/Swagger
conventions mechanically to GraphQL.

## Verify one vertical slice

Choose checks by changed behavior rather than a target test count:

1. Test domain invariants without frameworks, databases, or mocks where practical.
2. Test application decisions with small fake ports and failure injection.
3. Test inbound validation/error mapping using injected services; avoid requiring
   PostgreSQL for a pure transport contract.
4. Run adapter contracts/integration tests against real infrastructure when the
   claim depends on SQL constraints, locks, confirms, TTLs, or SDK behavior.
5. Run existing import guards. Inspect relative and cross-capability imports too.
6. Run relevant end-to-end flows. Read the checkout's README before supplying
   `LAB_TEST_*` URLs; use disposable resources and report infrastructure skips.

Do not describe green unit tests or skipped integration checks as proof of database
concurrency or end-to-end delivery. Do not provision production resources to
validate an architectural suggestion.

## Explain findings and decisions

Review in this order: business correctness, concurrency, reliability/security,
architecture, then maintainability. For each actionable finding provide:

- **Problem:** exact file/line and a concrete trigger or reproduction.
- **Impact:** observable failure and the affected invariant/boundary.
- **Solution:** the smallest boundary-restoring change and a verification scenario;
  offer hints instead of a complete exercise solution unless requested.

Separate confirmed defects from nonblocking improvements, assumptions, and known
lab trade-offs. Avoid duplicate comments. Explain why a port/refactor earns its
cost; prefer a small behavior-preserving extraction to a rewrite. Record important
decisions in `docs/decisions/` when appropriate. Never add microservices, Kafka,
generic repositories, DI containers, or universal CQRS/event sourcing just to
fit a pattern.

## Attribution

Adapted for this repository from Affaan Mustafa's ECC
[hexagonal-architecture skill](https://github.com/affaan-m/ecc/blob/b38be6a7f6350964d59328b52f0624e1d1d552d1/skills/hexagonal-architecture/SKILL.md),
listed on [skills.sh](https://www.skills.sh/affaan-m/ecc/hexagonal-architecture).
Preserve the bundled [MIT license](LICENSE) when redistributing this adaptation.
