# Inventory DDD skeleton
## Objective and authorized scope
Build the first inventory slice under src/ using DDD and hexagonal boundaries.
User explicitly requests implementation with TDD and future Flask compatibility.
Preserve the documented inventory rules; do not implement the whole roadmap.
## Design and constraints
- Inventory is the top-level business capability; domain, application, adapters live beneath it.
- Domain identity is client + SKU + warehouse + location, a provisional lab scope.
- Pure domain balance validates quantities and supports receiving; advanced operations remain exercises.
- A read-only GetInventory use case depends on a repository Protocol, implemented in memory.
- No Flask, database, queue, production concurrency solution, or generic repository framework.
- Preserve unrelated files and the untracked .codegraph/ index.
## Workflow
- TDD: ON, explicit user request. Runner: uv run pytest (pytest dev dependency).
- Observe RED before each behavior implementation, then GREEN and refactor.
- Route: delegated direct for both tasks; mapping needs 4+ context files,
  implementation needs 2+ non-trivial files. Read-only mapping completed.
- Baseline: d509545. Feature branch: feat/inventory-ddd-skeleton.
- Delivery: ask-on-risk. Revised forecast: approximately 470 authored changed lines,
  counting rename-aware additions + deletions; generated lockfile excluded.
- RDD: on by default; assess each committed work unit against last boundary.
## Tasks and acceptance
- [x] T1: Configure src packaging and pytest; migrate the starter into inventory/domain;
  introduce immutable identity and enforce current balance invariants, implement receive.
  Keep allocation/pick/pack/ship hints rather than solving those exercises.
  Checks: observed failing domain tests, then passing domain tests; no duplicate old package.
  Route: delegated writer (multiple non-trivial files).
- [ ] T2: Add repository read port, GetInventory use case, in-memory adapter and concise setup/
  architecture docs; test found/missing identities, client/location isolation and inward dependencies.
  Checks: observed RED then GREEN, full pytest suite, installed-package smoke check, diff check.
  Route: delegated writer (multiple non-trivial files).
## Evidence and progress
- Mapping: CodeGraph contains zero indexed files; direct inspection used after explore failed.
- TDD environment: Python 3.13.14 available; pytest absent, uv available.
- T1 RED: uv run pytest tests/inventory/test_domain.py: 6 failed, 22 passed (receive TODO); initial missing-import RED also observed.
- T1 GREEN/refactor: uv run pytest: 28 passed; domain smoke available=2; diff check clean.
- T1 commits/native assessment pending; minimum Python 3.11 declared, tested with 3.13.14 only.
- Packed is nonnegative only; its subset semantics intentionally remain a modeling exercise.
- Runtime HTTP harness: N/A; no HTTP adapter is in scope. Exercise the application in process.
- Rollback: remove the new skeleton/config/tests/docs and restore inventory/domain.py from baseline.
## Next step
Commit T1 on domain child branch, assess risk, then implement T2 with observed RED/GREEN on application child branch.


- Delivery update: T1 staged diff is about 324 authored additions/deletions excluding generated uv.lock; Git does not detect the changed module as a rename. Full skeleton exceeds about 400 lines. User accepted recommended feature-branch-chain; no push or PR is authorized.

## Local delivery chain
- Tracker: feat/inventory-ddd-skeleton (baseline d509545). No remote tracker PR created.
- Slice 1: feat/inventory-ddd-skeleton-domain targets tracker; domain/config/tests (T1).
- Slice 2: feat/inventory-ddd-skeleton-application targets domain child; use case/adapter/tests/docs (T2).
- PR creation, pushes and merges remain user decisions.
