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
- [x] T2: Add repository read port, GetInventory use case, in-memory adapter and concise setup/
  architecture docs; test found/missing identities, client/location isolation and inward dependencies.
  Checks: observed RED then GREEN, full pytest suite, installed-package smoke check, diff check.
  Route: delegated writer (multiple non-trivial files).
## Evidence and progress
- Mapping: CodeGraph contains zero indexed files; direct inspection used after explore failed.
- TDD environment: Python 3.13.14 available; pytest absent, uv available.
- T1 RED: uv run pytest tests/inventory/test_domain.py: 6 failed, 22 passed (receive TODO); initial missing-import RED also observed.
- T1 GREEN/refactor: uv run pytest: 28 passed; domain smoke available=2; diff check clean.
- T1 commit: e75be85 on feat/inventory-ddd-skeleton-domain. Minimum Python 3.11 declared; tested with 3.13.14 only.
- Native assessment d509545..e75be85: medium, slice_budget_reached, 411 total lines (332 authored, 79 generated lockfile). User granted review; native reliability review approved with no findings and exact acknowledgement completed.
- Review lineage review-8d4c6227e9435bce; committed-only base d509545. Exclude untracked .codegraph/.
- Packed is nonnegative only; its subset semantics intentionally remain a modeling exercise.
- Runtime HTTP harness: N/A; no HTTP adapter is in scope. Exercise the application in process.
- Rollback: remove the new skeleton/config/tests/docs and restore inventory/domain.py from baseline.
## Next step
Both implementation tasks are complete. Commit T2, assess native review from e75be85, then record its exact commit and assessment. No application-branch push or PR authorized.


- Delivery update: T1 staged diff is about 324 authored additions/deletions excluding generated uv.lock; Git does not detect the changed module as a rename. Full skeleton exceeds about 400 lines. User accepted feature-branch-chain and requested push; destination/configured SSH identity explicitly authorized for domain branch push. PR/merge not authorized.

## Local delivery chain
- Tracker: feat/inventory-ddd-skeleton (baseline d509545). No remote tracker PR created.
- Slice 1: feat/inventory-ddd-skeleton-domain targets tracker; domain/config/tests (T1).
- Slice 2: feat/inventory-ddd-skeleton-application targets domain child; use case/adapter/tests/docs (T2).
- PR creation, pushes and merges remain user decisions.

- T1 review completed: native reliability lens found no issues; reviewer did not independently run tests. Parent reran uv run pytest -q: 28 passed. Last reviewed boundary advances to e75be85.
- User requested review and push. No remote probe or connection made; only local git remote configuration read. Confirm push of feat/inventory-ddd-skeleton-domain to origin git@github.com:Stefano-Mazziotta/warehouse-fulfillment-lab.git using configured Git SSH identity.

- Push completed: origin/feat/inventory-ddd-skeleton-domain created at e75be857f3f6232f9b006df1a664ca7aa64b3267 using authorized configured Git SSH identity; upstream tracking configured. Only committed T1 files pushed; uncommitted task progress remains local.

## T2 verification
- Delegated writer observed behavioral RED: uv run pytest tests/inventory/test_application.py tests/inventory/test_in_memory.py: 8 failed (NotImplementedError stubs); GREEN: 8 passed.
- Full suite: uv run pytest -q: 38 passed on Python 3.13.14; domain/application static inward-import guards included.
- Parent built a wheel with uv build --wheel --out-dir <temporary-directory> and installed it in an isolated uv environment outside checkout using Python 3.13.14. Found available=5; missing owner raises InventoryNotFound; import resolves to site-packages.
- git diff --check clean. HTTP harness remains N/A: Flask deliberately absent.
- Source: read port, GetInventory, seeded in-memory adapter; application tests use an independent stub, adapter tests isolate all four identity dimensions. README documents future Flask boundary.
- Rollback T2: remove its application/adapters modules, three tests and README; keep T1 domain intact.
- T2 implementation commit/assessment: pending.
