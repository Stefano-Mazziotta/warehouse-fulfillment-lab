# Inventory layer modularization

## Objective and authorized scope
Make inventory domain concepts explicit and use domain/application/infrastructure layers.
Preserve all business behavior and unfinished learning exercises; no infrastructure dependencies or remote operations.

## Plan and constraints
- [x] T1: Extract domain identity/errors and application errors; rename adapters to infrastructure; update imports, architecture checks and README; verify and commit.
- Route: delegated direct. Mapping/preparation requires 4+ files; writer touches multiple non-trivial files. Read-only mapping completed.
- Keep invariants and stock operations in InventoryBalance; avoid artificial rules services.
- TDD ON, explicit prior user choice recorded in odd/tasks/inventory-ddd-skeleton.md. Runner: uv run pytest. Observe failing new import/boundary tests before refactor, then GREEN.
- Acceptance: explicit layers; independent domain/application; stable domain facade; receive/invariants unchanged; allocation/pick/pack/ship remain exercises.
- Checks: full pytest suite, import smoke check, git diff --check. HTTP harness N/A: no HTTP boundary.
- Rollback: revert this refactor work unit, restoring adapters and original domain/application module placement.
- Delivery: ask-on-risk; forecast approximately 220 authored additions/deletions, generated files excluded. One local work-unit commit; no PR/push.
- RDD: on by default; assess committed unit against branch point and follow native transitions.

## Progress and evidence
- Initial state: master, tracked tree clean; preserve untracked .codegraph/.
- Writer observed baseline 38 passed, then RED: two missing new-layer imports during pytest collection; GREEN: 39 passed.
- Import smoke confirmed extracted domain facade class identity and infrastructure-backed read with available=5.
- README explains identity, balance invariants, application errors and layer responsibilities. Behavior/exercise stubs unchanged.
- git diff --check passed. HTTP harness N/A: no HTTP adapter.
- Engram initial mirror saved and read back as observation 1600.
- Work-unit commit: f58ee0d. Parent full suite: 39 passed in 0.05s; diff check clean.
- Native assessment from branch point b2ccc0f: medium, 140 lines, under_budget; review_due=false. Initial assessment required explicit exclusion of unrelated .codegraph/; rerun succeeded. No review approval claimed; slice remains pending under budget.
- Next: learner studies modules and implements allocation as a separate exercise. No feature work remains.
