# Flask adapter scenarios

Choose cases for changed behavior; do not add the entire checklist for an unrelated
edit. Keep test contracts in the API layer.

| Change | Evidence |
| --- | --- |
| Factory/config | Independently configured apps, fake injection, no import-time I/O, invalid-setting failure |
| REST errors | Intended JSON 400/404/405/500; preserved status/Allow; safe unexpected-error text |
| GraphQL errors | Stable extension codes/nullability; no infrastructure detail in responses |
| Tenant context | Owner scoped once; no nested override; read/write isolation |
| Webhook acceptance | Validation before persistence; durable evidence; documented sync/queued outcome |
| Duplicate event | Same ID/body harmless; changed body follows conflict policy; authoritative evidence processed |
| Pagination | Omitted/null/variable/default limits agree; stable ordering; invalid cursor rejected |
| Query budget | Aliases, acyclic fragment DAGs, cycles, defaults, fan-out and large inputs bounded |
| DataLoader | Tenant/request isolation, bounded statement count, freshness after writes |
| Lifetime | No durable task relies on a closed request loop or leaked context |
| Logging | Correlation survives failure; no raw queries/secrets; no fallback stderr leak |
| Docs | Examples match parser/schema and explain retryable outcomes |

Construct fresh apps with explicit fake services for edge-only behavior. Use
`create_app` seams where present; do not initialize production adapters merely to
test a missing header or bad body. Run these cases without LAB_TEST_DATABASE_URL
to prove they do not silently skip.

Retain service-backed tests for constraints, locks, rollback, routing and full
fulfillment. SQLite/mocks cannot replace those proofs. Prefer existing Strawberry
types and explicit REST parser/serializer functions before adding extensions.
