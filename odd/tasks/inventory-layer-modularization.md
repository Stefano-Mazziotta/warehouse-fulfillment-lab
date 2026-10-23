# Inventory layer modularization

## Objective and authorized scope
Make inventory domain concepts explicit and use domain/application/infrastructure layers.
Preserve all business behavior and unfinished learning exercises; no infrastructure dependencies or remote operations.

## Plan and constraints
- [x] T1: Extract domain identity/errors and application errors; rename adapters to infrastructure; update imports, architecture checks and README; verify and commit.
- [ ] T2: Use class-corresponding snake_case module names, clarify class responsibilities, update imports and README; verify and commit. Authorized by follow-up request for clean-code readability.
- T2 route: delegated writer; mapping/preparation spans 4+ files and six non-trivial modules. Preserve T1 evidence and behavior.
- Route: delegated direct. Mapping/preparation requires 4+ files; writer touches multiple non-trivial files. Read-only mapping completed.
- Keep invariants and stock operations in InventoryBalance; avoid artificial rules services.
- TDD ON, explicit prior user choice recorded in odd/tasks/inventory-ddd-skeleton.md. Runner: uv run pytest. Observe failing new import/boundary tests before refactor, then GREEN.
- Acceptance: explicit layers; independent domain/application; stable domain facade; receive/invariants unchanged; allocation/pick/pack/ship remain exercises.
- Checks: full pytest suite, import smoke check, git diff --check. HTTP harness N/A: no HTTP boundary.
- Rollback: revert this refactor work unit, restoring adapters and original domain/application module placement.
- Delivery: ask-on-risk; revised total forecast approximately 260 authored additions/deletions with rename detection, generated files excluded. Local work-unit commits; no PR/push.
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
- T1 evidence commit: 833f722; final initial slice assessment 142 lines, medium/under_budget.
- T2 scope: inventory_balance.py, inventory_key.py, inventory_error.py, inventory_repository.py, inventory_not_found.py, in_memory_inventory_repository.py. Keep GetInventory and domain facade stable; avoid new abstractions.
- T2 checks: observed RED on updated module imports, then uv run pytest GREEN; import smoke and diff check. No new behavior is authorized.
- T2 RED: uv run pytest reported two ModuleNotFoundError collection errors after updated test imports, before source renames. GREEN: 39 passed in 0.06s.
- T2 smoke: all renamed modules import, domain facade class identities match, successful read and missing read pass. No stale active module paths found; diff check clean.
- T2 authored source/test/README change: approximately 46 lines with rename detection, before final line wrapping. No rule behavior changes.
- T2 rollback: revert its six module renames, dependent imports, class descriptions and README updates; T1 layers remain intact.
- Next: commit T2 and assess against b2ccc0f (pending slice boundary).
