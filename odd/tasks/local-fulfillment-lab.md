# Local fulfillment interview lab

## Outcome and authorization
Implement the approved local order-to-shipment interview lab. Agent builds tested slices; learner studies rules, failure drills and decisions. Target November 30, 2026; learner budget 15–20 hours/week. User explicitly approved implementation and local feature-branch-chain. No push, PR, cloud deployment, external accounts or hosted telemetry authorized.

## Scope and constraints
- Modular monolith with domain/application/infrastructure per capability; explicit class-corresponding filenames and English artifacts.
- Python/Flask, PostgreSQL/SQLAlchemy/Alembic, Strawberry GraphQL, RabbitMQ/Pika, Valkey, bounded DynamoDB Local and local Sentry transport exercises.
- Owner isolation, one warehouse per order, all-or-nothing allocation, deterministic stock lock ordering, partial picks, multiple packages, cancellation before picking, uncertain shipment reconciliation.
- Packing belongs to packages, not a balance-wide counter. Picked reservation source remains accounting reference; physical staging transfers excluded.
- Durable inbox/outbox, idempotent consumers, bounded retries/DLQ, reconciliation and failure drills.
- Exclude frontend, auth system, real carrier connections, EDI compliance, optimization, microservices and Kubernetes.
- TDD ON: prior explicit user choice; exact runner `uv run pytest`. Require observed RED/GREEN then refactor; integration proofs use real local services.
- RDD OFF, global setting verified. Ordinary tests remain mandatory; report disabled/unmanaged, never run native review while disabled.
- Delivery ask-on-risk, approved feature-branch-chain. Forecast 3,000–5,000 authored additions/deletions across full lab; size is advisory per task. Keep cohesive tests/docs with work-unit commits; no code compression or artificial splitting.
- Tracker branch feat/local-fulfillment-lab; baseline 66e63196281317602bbcd76cf5a1f8979fd60335. First child targets tracker; subsequent children target immediate predecessor. No remote tracker PR.
- Preserve untracked .codegraph/ and docs/Untitled-2026-10-18-1954.excalidraw. Do not touch other projects' containers.

## Task ownership and dependencies
| ID | Depends | Ready when | Route | Owner | Exclusive files | Validation | Status |
|---|---|---|---|---|---|---|---|
| T1a | — | baseline verified | delegated: domain/tests/docs | allocation worker | inventory domain + domain tests, allocation study note | invalid/insufficient/repeated allocation, unchanged original | [x] |
| T1b | T1a | domain proofs pass | delegated: persistence/config | persistence worker | inventory application/infrastructure, migrations, Compose, pyproject, integration tests | real PostgreSQL concurrent last-unit + rollback/isolation/migrations | [x] |
| T2 | T1b | concurrency proof passes | delegated: multiple capabilities | fulfillment worker | orders/picking/packing/shipping and related tests | valid/invalid transitions, quantity reconciliation, carrier unknown outcome | [ ] |
| T3 | T2 | fulfillment demo passes | delegated: integration boundaries | messaging worker | integrations/messaging/worker, related tests | outbox, duplicate/redelivery, bounded retries/DLQ/reconciliation | [ ] |
| T4a | T3 | reliable flow passes | delegated: HTTP/contracts | API worker | Flask/GraphQL API and API tests | business endpoints, pagination/query limits/batching counts | [ ] |
| T4b | T4a | API proof passes | delegated: adapters and diagnostics | infrastructure worker | cache/projection/telemetry + tests | Valkey outage, DynamoDB projection, local error capture, EDI fixtures | [ ] |
| T5 | T4b | feature freeze | delegated: learning assets | study worker | demos/study guides/failure scripts | full demo,8 failure drills,AWS map,mock interview checklist | [ ] |

## Ready now
- T2: order-linked reservations and multi-balance order transaction. T1a/T1b proofs pass.

## Blocked
- T3 waits on T2; T4a waits on T3; T4b waits on T4a; T5 waits on T4b.

## Shared contracts
- Coordinator owns task tracker and cross-slice interface decisions. Child workers get exclusive file lists; Compose and package config handed to one worker at a time.
- API/worker share application use cases; domain/application never import Flask, SQLAlchemy, messaging or cache libraries.
- PostgreSQL is authoritative; cache/projections cannot authorize allocations. Broker delivery is not exactly-once business execution.

## Runtime and evidence
- Baseline:39 tests pass on Python3.13.14; no framework/db dependencies yet. Docker daemon29.9.1 and Compose5.6.0 available; postgres16-alpine cached.
- Host5432 belongs to another project; lab uses loopback55432 after availability check. Never reuse unrelated database/container.
- HTTP harness initially N/A (no HTTP adapter); T1 runtime proof is PostgreSQL integration.
- Per-task closure records observed tests, commit, authored line count, rollback and native review disabled/unmanaged.
- Initial Engram mirror synchronized and read back, observation1739.
- T1a RED:13 allocation tests failed with NotImplementedError; GREEN:52 passed. Parent independently reran52 passed; diff check clean. Validates exact positive integer, insufficient stock, original preservation and repeated reservations.
- T1a rollback: revert allocation method, its13 tests and docs/study/inventory-allocation.md. HTTP harness N/A: pure domain slice. Native review disabled/unmanaged.
- Host55432 confirmed free; cached PostgreSQL16-alpine image confirmed. No other container touched.
- T1a commit883de37 on feat/local-fulfillment-lab-allocation; parent branch feat/local-fulfillment-lab. Slice121 authored additions/deletions. Tracker initialization80b8e59 is49 lines; running170 lines. No remote delivery.
- T1b RED: missing AllocateInventory module, then application tests pass; missing inventory_schema before DB implementation. Additional RED: failed transaction initialization did not close connection; fixed self-cleanup because __exit__ is not called when __enter__ fails.
- T1b GREEN: parent configured full run `LAB_TEST_DATABASE_URL=postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab uv run pytest -q`:67 passed in1.25s; git diff --check clean. Writer verified Alembic upgrade/downgrade/upgrade and actual pg_blocking_pids wait before releasing winner. Seven DB tests include migration/isolation/rollback/constraints/last-unit/missing/locked-save scenarios.
- T1b runtime: lab PostgreSQL healthy on127.0.0.1:55432; Alembic initial migration applied. Container intentionally remains running; `docker compose -p warehouse-fulfillment-lab down` preserves its volume. HTTP harness N/A: no API adapter yet.
- T1b rollback: against disposable lab DB only, downgrade migration then revert application transaction, PostgreSQL schema/adapters, tests/dependencies/Compose/runtime docs. Domain allocation remains intact.
- T1b delivery: feat/local-fulfillment-lab-postgres targets feat/local-fulfillment-lab-allocation. Natural coherent DB slice exceeds400 authored lines (tests/migration/rollback/runtime all retained); no code compression. No PR created; recommend size:exception or schema/runtime vs transaction slices before any future PR. Native review disabled/unmanaged.
- T2 preparation: do not loop single-balance allocation calls. New transaction must lock order, normalize repeated demand, lock balances in sorted full-key order and persist reservations/order/stock together. Location selection ascending location ID with split across locations within selected warehouse; cancellation cutoff is startPicking; shipment attempt covers all order packages.

## Next action
T1 inventory milestone complete; T2 is next. Orders/picking/packing/shipping/messaging/API/cache/projection/telemetry and final interview assets remain unimplemented; do not infer full-lab completion.
