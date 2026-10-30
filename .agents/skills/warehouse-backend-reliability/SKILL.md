---
name: warehouse-backend-reliability
description: Implement and review reliable Python WMS adapters and quality gates in warehouse-fulfillment-lab. Use for PostgreSQL/SQLAlchemy/Alembic transactions, RabbitMQ/Pika outbox/inbox flows, carrier/channel recovery, Valkey caches, DynamoDB projections, structured logging, EDI boundaries, Docker/uv reproducibility, or performance/verification work. Preserve the existing stack and mentor-first scope; do not provision infrastructure or add patterns without a requirement.
---

# Warehouse Backend Reliability

## Establish the guarantee

Read `AGENTS.md`, the checkout, changed files, relevant tests, task/decision records,
and installed dependency versions. Read [the stack map](references/stack-map.md)
for branch-specific adapters and [quality gates](references/quality-gates.md) to
select verification. Do not assume the feature-chain stack is on master.

State the invariant, owner scope, source of truth, local commit, remote effects,
retry identity, and observable failure. For learning, ask for the learner's failure
model before giving the complete mechanism. Work only on the authorized operation;
a skill does not authorize deployment, data resets or production services.

## Protect SQL transactions

- Keep SQLAlchemy/psycopg in adapters. Preserve Core and Alembic; do not add ORM
  sessions or Flask wrappers without a concrete requirement.
- Reuse engines/pools appropriately, acquire connections per execution, and close
  or roll back on every path. Do not share live connections/sessions across threads.
- Commit required stock, reservation, order and outbox changes together. Respect
  established isolation/lock ordering; analyze races before choosing locks,
  guarded updates or optimistic checks.
- Parameterize values, use explicit columns/constraints, and validate identity
  and numeric ranges. Never interpolate untrusted SQL identifiers; use a closed
  validated set or safe driver identifier composition when they must vary.
- Bound pool waits, connect/query/lock timeouts for the operation. Retry recognized
  transient failures only with a bounded policy, rolling back and restarting the
  whole unit of work rather than a statement in an aborted transaction.
- Justify indexes with actual filters/order and representative query plans. Avoid
  unbounded reads and per-row queries disguised as batching.
- Review migration compatibility, existing data, locks and recovery. Do not call
  destructive downgrades safe because they execute; preserve dedup/replay history.

## Recover distributed outcomes

Keep carrier calls outside SQL lock scopes. Persist a stable attempt and payload
before side effects when needed; verify the receipt's owner/order/attempt/packages.
A timeout is an unknown outcome, not proof of no effect. Reconcile using the
established carrier contract before creating another side effect.

Persist authoritative inbound evidence and outcome. Detect reused IDs with changed
payloads, scope provider IDs correctly, and encode composite keys unambiguously.
Advance checkpoints after page durability; analyze overlap, equal timestamps,
ordering, conflicts and failed records before claiming complete reconciliation.

Keep EDI at the edge: preserve partner/control-number scope, validate supported
delimiters/fields, and derive advice from the matching owned shipment. State parser
limits rather than claiming full X12 compliance.

## Inspect every messaging hop

Use the existing RabbitMQ/Pika path; do not add Celery/Kafka solely because a
tutorial mentions background tasks. Verify outbox writes share the business
transaction, inbox writes share local consumer effects, publishing precedes the
delivery mark, and acknowledgement follows commit. Expect duplicates in each gap.

Trace confirms, routing/mandatory behavior, persistence, retry publishing, TTL
dead-letter transfers and DLQ recovery separately. A publisher confirm is not a
consumer commit; durable queues and messages alone do not prove every hop loss-free.
Bound prefetch, attempts, timeouts and reconnect backoff. Validate payload/retry
metadata before arithmetic or dispatch so poison data cannot crash error handling.

Separate permanent from transient failures and define replay/operator evidence.
On shutdown, leave unfinished work unacknowledged. An inbox does not make a remote
side effect atomic with SQL: require remote idempotency or recoverable workflow.

## Keep derived state disposable

- **Valkey:** keep PostgreSQL authoritative, encode tenant keys safely, validate
  cached data and bound TTL/timeouts. Document cache-aside races. Fail open only
  for optional reads, never ownership, authorization, locking or idempotency.
- **DynamoDB projection:** use scoped keys and idempotent/conditional writes;
  handle duplicate/stale/reordered events, partial writes, pagination and outages.
  Rebuild from retained facts only; a projection is not authoritative order state.
- Preserve documented best-effort post-commit invalidation. Do not roll back or
  report a committed order as failed because an optional derived store is down.

## Observe failures and control scope

Use structured JSON and bounded request/event/attempt correlation. Preserve useful
server-side exception context without credentials, full payloads, sensitive SQL
parameters or raw GraphQL queries. Verify actual process output, including fallback
loggers, not only a selected captured logger.

Distinguish liveness and dependency readiness. When relevant, measure latency,
timeouts, pool pressure, outbox age, retry/DLQ depth and reconciliation lag. A
dashboard is not an alert: state actionable thresholds and a safe recovery path.

Keep Compose ports and credentials lab-scoped. Use lockfiles/frozen installs and
distinguish Python audits from image/supply-chain checks. Check advisories before
proposing upgrades; do not install tooling, alter lockfiles or pin unrelated
images as a side effect of review.

## Verify and report honestly

Use domain tests for invariants, fake ports for orchestration, shared adapter
contracts for interchangeability and real infrastructure for constraints, races,
confirms, TTLs and SDK semantics. Inject failures before/after commits and remote
actions; keep transport-only tests independent of databases.

Choose meaningful checks for the change, report commands/results/skips and state
unverified guarantees. Measure before optimizing and describe the dataset/query
counts supporting performance claims. Review using **Problem / Impact / Solution**
with location and reproduction. Separate defects, hardening and lab limitations;
publish or modify only within the task's authorization.

## Attribution

Project-specific synthesis informed by ECC's
[hexagonal-architecture](https://github.com/affaan-m/ecc/blob/b38be6a7f6350964d59328b52f0624e1d1d552d1/skills/hexagonal-architecture/SKILL.md)
and robust-skills'
[clean-ddd-hexagonal](https://github.com/ccheney/robust-skills/blob/0eea7b060d12e3520556a73b15fbfa79480987d1/skills/clean-ddd-hexagonal/SKILL.md).
Preserve the bundled [MIT notices](LICENSE). Ground technology guarantees in
installed-version documentation and observable evidence.
