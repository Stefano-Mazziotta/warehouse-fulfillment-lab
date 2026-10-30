---
name: warehouse-flask-api
description: Implement, review, and test Flask REST/webhook and Strawberry GraphQL adapters in warehouse-fulfillment-lab. Use for application factories, configuration, validation, safe errors, tenant scoping, pagination, DataLoader lifetime, API documentation, or web security/performance changes. Preserve the Python core and existing stack; not an instruction to add ORM/JWT/REST extensions or deploy the lab.
---

# Warehouse Flask API

## Establish scope

Read `AGENTS.md`, the touched code/tests, `pyproject.toml`, and `uv.lock`. Preserve
mentor-first learning; implement exercises only when requested. Inspect the
branch: master may have no web adapter yet. Do not scaffold Flask or install
packages just because this skill is invoked. Consult the architecture companion
only for a domain/dependency decision that the task actually raises.

Read [adapter scenarios](references/adapter-scenarios.md) when choosing tests or
changing contracts, errors or request lifetime. Prefer project conventions and
installed-version documentation to copied tutorial code.

## Compose an isolated application

- Configure and register views/blueprints in an app factory. Build concrete
  dependencies at the composition root and inject them into adapters. Avoid
  import-time connections, network calls, and global live transactions.
- Parse environment at the process edge. Validate required settings and numeric
  bounds early: page/depth/cost/body limits and timeouts. Keep secrets outside
  source control and connection details out of client errors and logs.
- Share engines/pools appropriately, acquire/release connections per operation,
  and avoid sharing connections/sessions across threads. Use Flask contexts for
  framework concerns, not business dependency lookup through `g`.
- Preserve SQLAlchemy Core and Alembic where present; do not add ORM sessions,
  Flask-SQLAlchemy, Flask-Migrate, or another config layer to fit a tutorial.

## Keep handlers thin and typed

Validate protocol shape, build an owner-scoped domain/application input, call the
use case, and serialize its outcome. Keep SQL, state transitions, stock decisions,
carrier behavior and retry policy out of handlers.

Use readable Python classes/functions, type hints on changed public boundaries,
small named helpers, and guard clauses where useful. Avoid blanket class bans,
untyped RORO dictionaries, broad catch-and-continue logic, and dense one-liners.

Validate required fields, exact types, nonempty identifiers, storage-compatible
quantity ranges, timezone-aware timestamps, and body/collection bounds before
side effects. Make malformed JSON, unknown-field, and changed-duplicate-payload
policies explicit rather than accepting them accidentally.

## Keep REST and GraphQL contracts distinct

- Use intentional REST methods/statuses, JSON content types, stable safe error
  codes and request correlation. Preserve HTTPException status and headers such
  as `Allow`; handle routing errors at app level. Return generic unexpected-error
  text and log the original server-side without sensitive payloads.
- Preserve GraphQL schema types, nullability, extension codes, and the difference
  between transport and resolver errors. Do not turn every business conflict into
  HTTP failure or every HTTP exception into a successful response.
- Explain what 202 acknowledges. Document synchronous business outcomes versus
  queued acceptance, and never acknowledge failed persistence as accepted.
- Maintain GraphQL SDL snapshots and a small REST/webhook contract with checked
  request/response examples, outcomes and retry/idempotency policy. Do not add
  Swagger, RESTX or Marshmallow for a GraphQL-only operation.
- Treat changes to names, types, and semantics as compatibility decisions. Prefer
  additive changes and document migrations for breaking contracts.

## Bound work and preserve lifetime

Use pagination caps, deterministic keyset order and validated cursors. Batch nested
GraphQL collections with tenant/request-scoped loaders; invalidate or prime
affected entries after mutations in the same operation.

Bound validation itself: aliases, fragments, variable/default page sizes, nested
collection fan-out, bytes and expensive input lists. Avoid exponential fragment
expansion. Measure SQL statement counts and latency before claiming improvement.

Respect Flask's WSGI model: `async def` does not increase worker capacity or make
blocking SQL/SDK calls nonblocking. If offloading is justified, preserve context
and connection ownership; never move a live connection across executor threads.
Do not use request-loop `asyncio.create_task` for durable work; use the established
worker path.

## Apply security to actual exposure

Treat client headers and unsigned fake webhooks as documented lab stand-ins, not
verified identities. Do not add authentication without scope. For requested
public/partner exposure, derive ownership from verified credentials, authorize
operations, verify webhook signatures/replay policy, and test cross-tenant access.
CORS does not authenticate callers.

Inspect relevant request limits, timeouts, allowed origins/hosts, debug mode and
data in errors/logs. Apply CSRF protection when cookie-based authentication makes
it relevant; do not prescribe JWT as a universal solution. Separate reproducible
vulnerabilities from optional production hardening and known local-lab decisions.

## Verify and report

Use factory-injected fake services for parsing, missing identity, safe errors,
query limits and schema tests. Set `TESTING` deliberately; disable propagation
explicitly in tests asserting production error responses. Retain real PostgreSQL
tests for persistence, isolation and full fulfillment flows.

Cover the changed behavior's success, malformed input, business rejection,
dependency failure, duplicate, tenant isolation, and multi-mutation cases where
relevant. Assert status/headers/content type, schema, and side-effect boundaries.
Keep domain/application tests runnable without Flask.

Review using **Problem / Impact / Solution** and evidence. Check existing comments
before posting and publish only when asked. Report skips/uncertainty accurately.

## Attribution and primary references

Modified for this WMS on 2026-10-30 from Mindrally's
[flask-python](https://github.com/mindrally/skills/blob/7682ca77710e0971eab4e0ae5dddfa281aea0ba5/flask-python/SKILL.md).
Preserve the bundled [Apache-2.0 license](LICENSE). Replace its mandatory extension
list and class restrictions with the repository's conventions.

Consult Flask [factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/),
[errors](https://flask.palletsprojects.com/en/stable/errorhandling/),
[testing](https://flask.palletsprojects.com/en/stable/testing/), and
[async guidance](https://flask.palletsprojects.com/en/stable/async-await/).
Use [OWASP 2025](https://top10.owasp.org/2025/) as a risk lens, not a compliance claim.
