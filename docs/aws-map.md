# AWS map: where each lab component would live, and what changes

This is a thinking aid, not a deployment plan. Nothing here is built, provisioned or priced:
no IaC, no cloud account, no deployed resource. The lab runs only on local Docker Compose and
a host Python process.

The point of the map is the **trade-offs**. For each component ask: what keeps working
unchanged, what behaves differently when it becomes a managed service, and which lab decision
would I have to defend in an interview.

## How to read the claims

AGENTS.md asks to separate three kinds of statements. Every row below is tagged:

| Tag | Meaning |
| --- | --- |
| **[V]** | Verified against official AWS documentation on **2026-10-28** (see [Sources](#sources)). |
| **[C]** | Industry convention or general engineering knowledge, not checked against a specific page. |
| **[P]** | A decision this project made (see the tracker decisions and the study notes). |
| **[A]** | Assumption I could not verify. Treat it as a question to check, not a fact. |

Nothing here describes ShipHero's internal architecture; the project is inspired by that kind
of system, not a copy of it. AWS products, limits and prices change: re-check before relying on
any [V] claim after the date above.

## Component map at a glance

| Lab component | Local today | AWS counterpart (candidate) | What stays the same | What changes |
| --- | --- | --- | --- | --- |
| Authoritative store | PostgreSQL 16 (`compose.yaml`) | RDS for PostgreSQL or Aurora PostgreSQL | SQL, row locks, isolation levels, `FOR UPDATE`, `SKIP LOCKED` | failover, connection limits, replica lag |
| Message broker | RabbitMQ (`rabbitmq-data`) | Amazon MQ for RabbitMQ, or SQS / SNS / EventBridge | the outbox and inbox in PostgreSQL | delivery semantics, DLQ and redrive, ordering model |
| Read cache | Valkey | ElastiCache for Valkey | cache-aside, TTL, "a miss is fine" | network path, failover, auth/TLS |
| Order projection | DynamoDB Local | DynamoDB | conditional writes, stage-as-version | capacity modes, hot partitions, Streams as an alternative feed |
| Logs | JSON to stderr, Alloy, Loki, Grafana | stdout/stderr, CloudWatch Logs, Logs Insights, Managed Grafana | the JSON-per-line contract | who ships, retention, query language |
| API and workers | Flask GraphQL on the host, worker processes | ECS on Fargate (or Lambda + API Gateway / AppSync) | stateless handlers, use cases | long-running consumers, DB connections |
| Secrets | env vars with lab-only values | Secrets Manager / SSM Parameter Store | read at startup | rotation, IAM-scoped access |
| EDI transport | fixtures, fake VAN | Transfer Family (SFTP/AS2), B2B Data Interchange | control-number idempotency | who terminates the protocol and parses X12 |
| Network and identity | loopback ports | VPC, security groups, IAM roles | nothing local to preserve | everything (conceptual only here) |

## The whole flow with AWS placement and failure boundaries

```text
 Sales Channel (Shopify-like)
      |  webhook (HTTPS, at-least-once)        poll (reconciliation, updated_at cursor)
      v                                              ^
 [ALB / API Gateway] -> Integration (Flask on Fargate)   <--- FAILURE BOUNDARY 1: the internet.
      |   validate, persist raw event, enqueue            Webhooks get lost or repeated; the
      v                                                    poller is the repair path.
 [RDS / Aurora PostgreSQL]  <-- the ONE authoritative store
      |  Order -> Allocation -> Picking -> Packing        <--- CONSISTENCY BOUNDARY: one DB
      |  (row locks, order + stock + outbox row            transaction per state change
      |   commit together)                                 (never held across a network call)
      v
 outbox rows (PENDING)
      |  relay: claim -> publish -> mark                   <--- FAILURE BOUNDARY 2: DB <-> broker.
      v                                                         Crash between publish and mark
 [Amazon MQ for RabbitMQ  |  SQS / SNS / EventBridge]            means a duplicate, never a loss.
      |  at-least-once, redelivery on missed ack
      v
 workers (Fargate tasks): inbox row + effect in ONE commit   <--- idempotent consumer boundary
      |                      |
      v                      v
 [DynamoDB] projection   [ElastiCache Valkey] cache       (rebuildable; never authorize allocation)
      |
 Shipping: ShipOrder commits attempt, THEN calls carrier     <--- FAILURE BOUNDARY 3: the carrier.
      |                                                          Timeout means UNKNOWN; look up by
      v                                                          attempt id before any create.
 Carrier API (UPS/FedEx adapter)  -- label, tracking number
      |
      v
 Tracking -> status pushed back to the Sales Channel      <--- FAILURE BOUNDARY 4: outbound
                                                                webhook/API to the channel, same
 EDI partners: [Transfer Family SFTP/AS2] -> [B2B Data           retry + reconcile story.
   Interchange X12 -> JSON] -> intake use case (inbox key sender:ISA13)

 Cross-cutting: stdout/stderr JSON -> [CloudWatch Logs] -> Logs Insights / [Managed Grafana]
                secrets -> [Secrets Manager]; identity -> IAM task roles
```

What the diagram says in one sentence **[P]**: PostgreSQL is the only source of truth, everything
else is a repairable copy, and every arrow that crosses a process or network boundary is
at-least-once with an idempotent receiver plus a reconciliation path.

## PostgreSQL -> RDS / Aurora PostgreSQL

**Unchanged [C]:** both are PostgreSQL. `SELECT ... FOR UPDATE`, isolation levels, deadlock
behavior and the `FOR UPDATE SKIP LOCKED` relay claim are engine semantics, so drills 1 and 5
teach the same lesson on RDS. The lock-ordering rule (sorted SKU/location) matters just as much.

**What changes:**

| Topic | Lab | AWS | Why it matters |
| --- | --- | --- | --- |
| Failover | none | RDS Multi-AZ keeps a standby; a Multi-AZ DB *instance* deployment standby does not serve reads, a Multi-AZ DB *cluster* has readable standbys **[V]**. Aurora promotes a replica to writer and requests fail briefly during the switch **[V]** | Code must treat a dropped connection as retryable. `AllocateOrder` is already safe to retry (repeat allocation is a no-op **[P]**), which is the property you want here. |
| Connection limits | one process, small pool | RDS Proxy pools and shares connections, can reduce oversubscription and keep client connections through failover **[V]** | Many Fargate tasks times the pool size can exhaust `max_connections`. Proxy is attractive, but check pinning (it pins sessions in some cases **[V]**) before assuming long transactions or session state are free. |
| Read replicas | none | Aurora Replicas: lag is "usually much less than 100 milliseconds" but varies with write rate **[V]**. RDS read replicas are asynchronous **[C]** | **Authoritative reads vs scaled reads.** Allocation, picking and shipping decisions must read the writer, inside the locking transaction. Only dashboards and list queries may tolerate lag. Same rule as "the cache never authorizes allocation" **[P]**. |
| Aurora vs RDS | n/a | Aurora has a shared cluster volume and up to 15 replicas **[V]**; RDS PostgreSQL is the plain engine | Aurora buys failover speed and read scale at a price and with some engine differences **[C]**. For a lab-sized workload plain RDS is the simpler honest answer. |
| Migrations | `alembic upgrade head` by hand | a deploy step, ideally a one-off task before new code | Downgrades in this lab are guarded because they destroy data; do not wire them into a pipeline. |

**Interview angle:** "Which reads must hit the primary, and what breaks if a replica is 200 ms
behind?" Answer with the allocation race: a stale `available` read is harmless only if the
locking transaction re-reads under lock.

## RabbitMQ -> Amazon MQ for RabbitMQ vs SQS / SNS / EventBridge

The lab picked RabbitMQ **[P]** because the consumer can ack *after* the inbox commit, the
retry/DLQ topology is explicit, and the broker is easy to run locally.

| Topic | RabbitMQ (lab) | Amazon MQ for RabbitMQ | SQS standard | SQS FIFO |
| --- | --- | --- | --- | --- |
| Delivery | at-least-once, redelivery if not acked | same engine semantics **[C]** | at-least-once, "more than one copy of a message might be delivered" **[V]** | at-least-once with deduplication on a message deduplication ID **[V]** |
| Ordering | per queue, broken by retry (drill 4) **[P]** | per queue **[C]** | best-effort, messages "may occasionally arrive out of order" **[V]** | strict within a message group ID, none across groups **[V]** |
| Consumer protocol | ack after commit | same | receive, process, then `DeleteMessage` before the visibility timeout expires **[V]** | same, and the next message of a group is held while one is in flight **[V]** |
| Failure -> retry | nack/requeue, retry queue with TTL | same | message reappears after the visibility timeout (default 30 s) **[V]** | same, per group |
| Dead letters | explicit DLQ queue (`DEAD` after limit) | same | redrive policy with `maxReceiveCount`, DLQ in the same account and Region **[V]** | a DLQ can break exact ordering **[V]** |
| Replay from DLQ | no tool yet (known gap) | no tool either | DLQ redrive is a managed feature **[V]** | same, with the order caveat |
| Operations | one container | managed broker; single-instance (one AZ) or three-node cluster across AZs **[V]**; a cluster page describes classic mirroring across nodes, so confirm quorum-queue support and version before designing around it **[A]** | no servers | no servers |
| Fan-out | exchange + bindings | same | one consumer group per queue; fan-out via SNS **[C]** | same |

**Ack-after-commit vs visibility timeout.** In RabbitMQ the lab acks only after the inbox row
and the handler effect committed (drill 5). SQS has the same idea with different mechanics: the
message is hidden for the visibility timeout and reappears if you do not delete it **[V]**. So:
(1) set the timeout above the handler's worst case or extend it with `ChangeMessageVisibility`
(12 hours maximum **[V]**); (2) a slow handler still causes a duplicate, because even inside the
window delivery is at-least-once **[V]**; (3) the inbox dedup stays mandatory.

**Why the outbox is still needed on any of them.** No managed broker joins a PostgreSQL
transaction **[C]**. The failure table in `docs/study/messaging.md` (commit then publish, or
publish then commit) is independent of the broker brand. SQS FIFO's deduplication window is
bounded **[V]** (the page describes a deduplication interval), so it cannot replace a durable
consumer-side key either **[C]**. EventBridge adds routing and, for its custom bus, ordered
delivery and replay **[V]**, but it is still a delivery service, not your transaction.

**Choosing, honestly:**

- Keep RabbitMQ semantics (priority, explicit exchanges, existing client code): Amazon MQ.
  Cost: you still operate queues, policies and client reconnect logic.
- Plain work queue with DLQ and no broker to run: SQS standard + idempotent consumer. This is
  the lowest-effort fit for this lab's worker pattern.
- Per-order ordering matters (state transitions): SQS FIFO with `message group = owner#order`,
  accepting the throughput and DLQ-ordering caveats. The lab instead uses a monotonic lifecycle
  stage as the version **[P]**, which works on any unordered transport.
- One event, many independent consumers and routing rules: SNS or EventBridge in front of queues.

## Valkey -> ElastiCache for Valkey

ElastiCache lists Valkey as a supported engine, with version pages up to 9.1 at the time of
writing, and states Valkey 7.2 and above carries the features of Redis OSS 7.2 **[V]**. Service
name, engine versions and node-based vs serverless options change often: **verify in the
console and current docs before choosing** (that is the "assumption" for anything newer than the
date above).

| Topic | Lab | AWS | Note |
| --- | --- | --- | --- |
| Role | cache-aside for order summaries, 30 s TTL **[P]** | same | A cache is a latency optimization, never a source of truth **[P]**. |
| Failure mode | errors become misses, 5 s cooldown, throttled warning (drill 7) **[P]** | same code works against a managed endpoint **[C]** | Add connect and read timeouts; a hung cache is worse than a down one. |
| Durability | none wanted | newer Valkey versions on ElastiCache advertise a durability option **[V]** | Do not use it to "upgrade" the cache into a store here; that would blur the authoritative-store rule **[P]**. |
| Access | `127.0.0.1:56379`, no auth | in a VPC, TLS and auth/IAM are typical **[C]** | Keys carry the tenant (percent-encoded parts) **[P]**; a shared cluster without per-tenant isolation relies on that key discipline. |

## DynamoDB Local -> DynamoDB

| Topic | Lab | AWS | Trade-off |
| --- | --- | --- | --- |
| Conditional writes | `attribute_not_exists(stage) OR stage < :stage` makes the projection monotonic **[P]** | the same condition expressions; a false condition rejects the write **[V]** | This is optimistic concurrency without a lock: a rejected write is the correct "stale event" signal, not an error to retry. |
| Capacity | none | on-demand (pay per request, no capacity planning) or provisioned (you set reads/writes) **[V]** | On-demand fits a spiky or unknown projection load; provisioned is for steady, forecastable traffic **[V]**. Pick on measurement, not habit. |
| Partitioning | PK `OWNER#client`, SK `ORDER#order` **[P]** | each partition is designed for up to 3,000 read units and 1,000 write units per second **[V]** | A single huge tenant concentrates traffic on one partition key. That is the hot-partition question: would you shard the key or accept the ceiling? Not solved in the lab. |
| Feed alternative | RabbitMQ consumer on its own queue **[P]** | DynamoDB Streams: time-ordered item changes kept up to 24 hours, per-item ordering **[V]** | Streams capture changes **to DynamoDB**, but our truth is PostgreSQL, so the projection must be fed from PostgreSQL events anyway. The decision (consumer, not relay, so slowness never holds the relay lock) stands. Streams would suit a *downstream* consumer of the projection table. |
| Rebuild | replay from the outbox **[P]** | the same | A 24-hour stream window **[V]** is not a rebuild source; the outbox is. |

## Loki / Grafana / Alloy -> CloudWatch and friends

The lab contract **[P]**: the backend writes one JSON object per line to stderr and knows
nothing about the log backend. That contract maps cleanly:

| Lab | AWS | Notes |
| --- | --- | --- |
| stderr redirected to `logs/backend.log`, Alloy tails it | container stdout/stderr; on ECS the `awslogs` driver passes STDOUT and STDERR to CloudWatch Logs, including on Fargate **[V]** | The application code does not change. The shipper moves from a sidecar-less file tail to the platform. |
| Loki + LogQL | CloudWatch Logs + Logs Insights **[C]** | Labels vs fields differ: we kept ids (`request_id`, `event_id`) in the log body, not as labels **[P]**. In Logs Insights JSON fields are queryable directly **[C]**. |
| Grafana dashboard | Amazon Managed Grafana, a managed Grafana with CloudWatch among its integrated data sources **[V]** | Whether it can query a self-hosted Loki or a Loki-compatible service is not confirmed on the page I read **[A]**. |
| Alloy / OpenTelemetry | AWS Distro for OpenTelemetry (ADOT), an AWS-supported OpenTelemetry distribution that can send logs, metrics and traces to CloudWatch, X-Ray and Managed Prometheus **[V]** | The lab has no metrics or traces yet (known gap). Check ADOT's current release/support status before adopting **[A]**; the page I read carried 2020-2023 dates. |

Operational notes to say out loud **[C]**: set retention explicitly (the lab has none), scrub
exception text before logs leave the process, and alarm on DLQ depth and on error rate, not
only on the existence of logs.

## Flask GraphQL API and workers -> ECS Fargate, or Lambda

| Topic | ECS on Fargate | Lambda + API Gateway / AppSync |
| --- | --- | --- |
| Model | containers without managing servers or EC2 clusters; each task has its own isolation boundary **[V]** | functions invoked per request **[C]** |
| Fit for the lab's API | the Flask app runs as it does today, behind an Application Load Balancer **[V]** | needs an adapter layer; the composition root (`create_app`) would be rebuilt per cold start **[C]** |
| Long-running consumers | natural: a worker is a service that loops over the queue | awkward: SQS event-source mapping works well for short handlers; a relay that polls PostgreSQL and a consumer holding a connection do not fit the per-invocation model **[C]** |
| DB connections | each task keeps a pool; scale tasks and pool together | each concurrent invocation may open connections; AWS recommends RDS Proxy for functions that open many connections **[V]** |
| GraphQL | self-hosted Strawberry (what we have) | AppSync is managed GraphQL with its own resolver model **[C]**; moving to it means rewriting resolvers and giving up the "thin adapter over use cases" being the only seam **[P]** |
| Cold starts, timeouts | none | real constraints on latency-sensitive mutations **[C]** |

**Reading:** keep the API and workers as containers. The architecture rule that matters is
independent of the compute choice **[P]**: use cases know nothing about Flask, Lambda or ECS, so
swapping the host is an adapter change. If asked "why not Lambda?", say the relay and consumers
are long-lived, connection-holding loops and you would not want to fight that model for a
modular monolith.

## Secrets

Secrets Manager retrieves and rotates database credentials and API keys, replacing hard-coded
credentials with a runtime call **[V]**. SSM Parameter Store is the lighter option for
non-rotating configuration **[C]**. RDS Proxy can read database credentials from Secrets
Manager **[V]**. The lab's credentials are local values committed on purpose; the production
rule is the opposite: nothing in the repo, task roles read what they need **[C]**.

## EDI transport

Conceptual only; the lab parses fixtures and does not model transport **[P]**.

| Layer | Lab | AWS |
| --- | --- | --- |
| Transport | none (fake VAN) | AWS Transfer Family offers managed SFTP, FTPS, FTP and AS2 into S3 or EFS **[V]**; AS2 is called out for B2B and supply-chain use **[V]** |
| Translation | minimal X12 reader (not a validating parser) **[P]** | AWS B2B Data Interchange transforms and generates EDI (X12, EDIFACT, HL7v2) to and from JSON and XML **[V]** |
| Intake | `sender:ISA13` as inbox key, then idempotent `CreateOrder` **[P]** | the same use case, fed from a queue or an S3 event **[C]** |

The business questions stay unchanged: duplicate document (drill 8), a changed payload under
the same control number, acknowledgements (997/999 are not built), and who the sender really is.
Today the tenant comes from the unauthenticated ISA06 sender id **[P]**; with AS2 a partner
identity is authenticated at the transport, which is a real improvement and the first thing to
say about it **[C]**.

## Networking and IAM (conceptual)

- Put the database, cache and brokers in private subnets; only the load balancer is public **[C]**.
- One IAM task role per workload (API, relay, consumer) with least privilege: the consumer needs
  its queue and the DynamoDB table, not the Secrets Manager secret of the API **[C]**.
- Security groups express "API may reach PostgreSQL on 5432"; the lab's loopback-only ports are
  the local equivalent **[C]**.
- RDS Proxy must sit in the same VPC as the database and is not publicly accessible **[V]**.

## What I would NOT build for this lab

| Skipped | Why (AGENTS.md: "Avoid Overengineering") |
| --- | --- |
| Kubernetes | A single modular monolith with two or three process types does not need a cluster scheduler. It would teach cluster operations, not fulfillment. Fargate or even one VM covers the learning goal. |
| Terraform / any IaC | The lab's goal is to explain the domain and failure modes. IaC for a system that never deploys is unverifiable busywork; the diagram and trade-offs are the deliverable. |
| Microservices | The consistency boundary (order + stock + outbox in one transaction) is easy in one PostgreSQL database and hard across services. Splitting early would replace a lock with a distributed-transaction problem the lab has not earned. |
| Kafka / event sourcing / CQRS everywhere | No concrete requirement; the outbox + queue + projection already shows the useful ideas. |
| Multi-region, Global Database | Real, but it multiplies reconciliation questions before the single-region ones are understood. |
| A cloud account or deploy script | Authorized scope is local only. This document is reading material. |

## Questions this map should let you answer

1. "You moved to RDS with a read replica. Which queries may use it and which may not?"
2. "SQS standard delivered a message twice. What in your design makes that harmless?"
3. "Why keep an outbox if the broker is managed and durable?"
4. "Would you feed the projection from DynamoDB Streams? Why or why not?"
5. "Lambda or containers for the relay and consumers? What breaks at 200 concurrent invocations?"
6. "Where does the partner's identity get authenticated in an EDI flow?"
7. "Your tenant is one very large client. What does DynamoDB do to you?"

## Sources

Official AWS documentation, fetched 2026-10-28. Pages can change; the date is the check date.

- ElastiCache engine versions (Valkey): <https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/engine-versions.html>
- SQS standard queues: <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html>
- SQS visibility timeout: <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html>
- SQS dead-letter queues: <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html>
- SQS FIFO delivery logic: <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues-understanding-logic.html>
- Amazon MQ for RabbitMQ deployment options: <https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-broker-architecture.html>
- EventBridge overview: <https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html>
- DynamoDB condition expressions: <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html>
- DynamoDB throughput capacity modes: <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/capacity-mode.html>
- DynamoDB partition key design: <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html>
- DynamoDB Streams: <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html>
- RDS Proxy: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html>
- RDS Multi-AZ deployments: <https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html>
- Aurora replication and replicas: <https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.Replication.html>
- Lambda with RDS: <https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html>
- ECS awslogs driver: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using_awslogs.html>
- AWS Fargate for ECS: <https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html>
- Amazon Managed Grafana: <https://docs.aws.amazon.com/grafana/latest/userguide/what-is-Amazon-Managed-Service-Grafana.html>
- AWS Distro for OpenTelemetry: <https://aws-otel.github.io/docs/introduction>
- Secrets Manager: <https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html>
- AWS Transfer Family: <https://docs.aws.amazon.com/transfer/latest/userguide/what-is-aws-transfer-family.html>
- AWS B2B Data Interchange: <https://docs.aws.amazon.com/b2bi/latest/userguide/what-is-b2bi.html>

### Not verified (treat as open questions)

- Amazon MQ for RabbitMQ quorum-queue support and current engine versions (the cluster page I
  read describes classic mirroring; a first fetch of another page returned only a title).
- Whether Amazon Managed Grafana can query a Loki data source.
- ADOT's current maintenance status.
- RDS (non-Aurora) read replica lag characteristics, SNS, API Gateway, AppSync, SSM Parameter
  Store and CloudWatch Logs Insights behavior: stated from general knowledge, tagged **[C]**.
- Any pricing, quota or Region claim. None is made on purpose.
