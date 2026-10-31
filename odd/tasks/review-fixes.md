# review-fixes

Objective: resolve the 18 open review threads on chained PRs #11–#16, fixing each on the PR that introduced it.
Plan: `~/.claude/plans/check-the-code-review-stateless-candle.md`
TDD: enabled (Strict), runner: `uv run --frozen pytest -q`. Baseline: 633 passed, 264 skipped.
Delivery: fix per branch in chain order, then restack descendants. Push/merge are the user's decisions.

## Ownership
- Claude: F5, F12, F13, F14, F15, F17, nonblocking items
- User (mentor mode): F1, F2, F3, F4, F6, F7, F8, F9, F10, F11, F16, F18

## Tasks
- [x] F1 #11 attempt-ID collision (done by claude on explicit request) — 59a5496 (shipping)
- [x] F2 #12 event-ID collision (claude, on request) — 5a4cbba (messaging)
- [x] F3 #13 invalid x-attempt header (user)
- [x] F4 #13 shutdown between deliveries (user)
- [x] F5 #13 document best-effort TTL dead-letter hop (claude) — a0fde07 (broker)
- [x] F6 #14 channel event-ID collision (claude, on request) — 8a296d3 (reconciliation)
- [x] F7 #14 authoritative stored envelope (user)
- [x] F8 #14 overlap pagination cursor (user)
- [x] F14 #15 adapter tests without PostgreSQL (claude) — 9300006 (graphql)
- [x] F9 #15 fragment DAG traversal budget (user)
- [x] F10 #15 effective default page size (user)
- [x] F11 #15 DataLoader freshness across mutations (user)
- [x] F12 #15 JSON error boundary + MAX_CONTENT_LENGTH (claude) — 7556445 (graphql)
- [x] F13 #15 webhook REST contract (claude) — 46cbef3 (graphql)
- [x] F15 #16 Strawberry NullHandler (claude) — 99e1f43 (adapters)
- [x] F16 #16 advice writer order ownership (user)
- [x] F17 #16 outbound X12 delimiter guard (claude) — 939f5ee (adapters)
- [x] F18 #16 reject multiple ST (user)
- [x] NB #10 get_packages helpers; #17 README/setup; #5 CI

## Evidence
(commits recorded per task)

## Restack follow-ups
- F1 changes attempt IDs: on restack, replace 4d3e2336-7c55-5306-a2d6-3de5784db19f in fixtures/edi/945_*.edi and 856_*.edi (adapters branch #16) with the new ID for ACMEBRANDS/SO-1001.
- Shared encoding helper dropped: each bounded context encodes inline with json.dumps (no cross-context coupling).

## Closure (2026-10-30)
- All 18 findings plus the nonblocking items are fixed, one commit per finding, test-first. Commit hashes above are pre-restack; the chain was rebased bottom-up (one conflict each in #12 imports, #16 app_factory request-ID, #16 consumer runner logging; all resolved by keeping both behaviours).
- Final head feat/local-fulfillment-lab-learning: 687 passed, 260 skipped without services; 935 passed, 12 skipped with Postgres, RabbitMQ, Valkey and DynamoDB Local up (baseline 633/264). Remaining skips need LAB_TEST_DEMO/DRILLS/LOKI/VALKEY_DOWN. EDI fixtures regenerated for the new attempt ID.
- Not verified: the CI workflow on GitHub Actions, demo/drill/Loki live suites.
- Not done / open: push, thread replies+resolution, optional extra work budget for F9.
