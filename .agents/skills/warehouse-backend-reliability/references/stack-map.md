# Backend stack and boundary map

Inspect the current checkout and lockfile before using this table. At the master
baseline `b2ccc0f`, only the inventory skeleton is implemented; the extended
technologies below belong to the unmerged fulfillment chain reviewed in #5–#17.
Do not install them merely to make master match the table.

| Technology/capability | Branch-dependent role | Boundary to preserve |
| --- | --- | --- |
| Python 3.11+ and uv/pytest | Typed domain/use cases, frozen environment, layered tests | Use supported syntax and locked versions; separate pure and service-backed evidence |
| PostgreSQL + SQLAlchemy 2.0 Core + psycopg | Authoritative stock, orders, reservations, packages, attempts, outbox/inbox | Short explicit transactions, constraints, owner scope, deterministic locks |
| Alembic | Schema evolution and downgrade guards | Review existing data, DDL locks, application compatibility and information loss |
| Flask async extra + Strawberry GraphQL | Factories, REST/webhooks, thin resolvers, DataLoaders | Delegate HTTP/schema concerns to warehouse-flask-api; keep core framework-free |
| RabbitMQ + Pika | Publisher confirms, manual acknowledgements, retry/DLQ, projection consumers | Distinguish each transfer guarantee and bound recovery |
| Valkey client | Optional order-summary cache | Tenant-safe keys, bounded staleness, measured hit/miss/outage behavior |
| boto3 + DynamoDB Local | Derived order projection and rebuild | Conditional/idempotent updates, event completeness, emulator limitations |
| Durable fake carrier/channel | Repeatable timeout/reconciliation demonstrations | Treat fake contracts as explicit assumptions, not proof of a real provider's guarantees |
| JSON logging + Loki/Alloy/Grafana | Correlation, collection, investigation | No raw secrets/payloads; process output, retention and alerts are separate concerns |
| Representative EDI adapter | 850/940 intake and 945/856 advice | Partner identity, safe encoding, owned shipment correspondence, explicit parser limits |
| Docker Compose | Disposable local dependencies | Loopback exposure, named resource ownership, explicit prerequisites and cleanup |

## Locate the code

Discover files with `rg --files` rather than creating names from this guide.
When the fulfillment chain is present, inspect capability `domain`, `application`
and `infrastructure` directories, `migrations/`, `compose.yaml`, `observability/`,
and corresponding `tests/`. Core adapters on master still use `inventory/adapters`;
do not rename that folder as part of unrelated work.

Read the checkout's README, `docs/study/` notes and decisions when present. Use
its `LAB_TEST_*` values only for disposable services. Live demo/drill scripts can
create/delete lab rows or stop services: inspect ownership and cleanup before use.
Do not point failure drills at production or a shared database.

## Consult the technology's actual contract

- [SQLAlchemy 2.0 connections and transactions](https://docs.sqlalchemy.org/en/20/core/connections.html)
- [PostgreSQL concurrency control](https://www.postgresql.org/docs/current/mvcc.html)
- [Alembic operations](https://alembic.sqlalchemy.org/en/latest/ops.html)
- [RabbitMQ confirms and acknowledgements](https://www.rabbitmq.com/docs/3.13/confirms)
- [RabbitMQ dead-letter safety](https://www.rabbitmq.com/docs/3.13/dlx#safety)
- [Pika documentation](https://pika.readthedocs.io/en/stable/)
- [Valkey documentation](https://valkey.io/docs/)
- [DynamoDB conditional writes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html)
- [OWASP Top 10:2025](https://top10.owasp.org/2025/)

Select the documentation version matching the deployed service/client. A newer
guide or an emulator's success does not establish the behavior of another version.
