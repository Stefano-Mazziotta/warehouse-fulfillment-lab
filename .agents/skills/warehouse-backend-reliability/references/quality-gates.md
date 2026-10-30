# Quality gates for a WMS slice

Choose gates proportional to the behavior being changed. A skill/documentation
update needs metadata/link/example checks, not a new database migration. A locking
change needs real concurrent database evidence, not another mock assertion.

## Readability and design

- Use names from the domain glossary and narrow, explicit public contracts.
- Prefer typed domain/application values; keep `Any` at justified interop edges.
- Keep mapping and orchestration readable; extract a named helper when it makes
  identity fields, transitions or failure branches easier to audit.
- Avoid accidental mutation, hidden globals and broad exception suppression.
- Preserve backward compatibility or document the migration and rollback trade-off.
- Add comments/docstrings for non-obvious invariants, failure windows and decisions,
  not for restating a function name. Avoid speculative abstractions and rewrites.

## Select meaningful evidence

| Changed behavior | Required kind of evidence |
| --- | --- |
| Quantity, ownership, lifecycle rules | Pure valid/invalid domain cases and invariant preservation |
| Use-case orchestration | Fake-port outcomes, rollback behavior and failure injection |
| HTTP/GraphQL parsing or mapping | Factory-injected services and explicit protocol assertions |
| SQL locks/constraints/atomicity | Independent real PostgreSQL connections, deterministic contention, committed-state assertions |
| Outbox/inbox and routing | Commit/ack/publish crash windows, redelivery, changed duplicate IDs, retry exhaustion |
| Cache/projection | Outage fallback, key isolation, stale/reordered events, rebuild/partial-write windows |
| Query performance | Representative data, bounded statement counts, plans and before/after measurements |
| Migration | Upgrade/data compatibility and an honest downgrade/recovery assessment |
| Logging/security boundary | Actual output, safe correlation, failure visibility, no sensitive data |

Run the checkout's established commands, starting with frozen dependencies and
relevant tests, for example:

```sh
uv sync --frozen
uv run --frozen pytest -q
```

Inspect fixtures/README before enabling service-backed tests. Supply only URLs
for disposable resources; never treat unset LAB_TEST_* variables and skipped
proofs as end-to-end success. Do not invoke every live drill for a low-impact edit.

Run configured formatting, lint and type checks. If none exist, report that gap;
propose a separate scoped adoption of Ruff and one type checker where useful,
instead of claiming absent checks passed or adding tools during a review. Do not
write tests that simply mirror the implementation.

## Security and operational evidence

Use OWASP 2025 to inspect relevant risks: ownership/authorization, misconfiguration,
supply chain, injection, data integrity, safe logging and exceptional conditions.
Do not call a documented local fake credential a leaked production secret, or
claim JWT/CORS alone fixes authorization. For changed exposure, state the threat
model and verify the corresponding control.

Keep parameterized SQL, bounded inputs/timeouts/retries, resource cleanup and
replayable identities explicit. Check actual advisories for installed versions;
distinguish dependency scanning, container scanning and source review. An audit
with no known findings does not prove absence of vulnerabilities.

For delivery work, explain who sees failure and how an operator can investigate,
retry, reconcile or safely roll back. Do not claim observability/alerts exist from
the presence of a library, dashboard, or one happy-path log.

## Report completion

State what changed, the business effect, commands/results, and material remaining
risks. For findings use **Problem / Impact / Solution**, severity where justified,
location and a concrete trigger. Label improvements and unverified assumptions.
Do not inflate confidence, duplicate old comments, or approve/merge without scope.
