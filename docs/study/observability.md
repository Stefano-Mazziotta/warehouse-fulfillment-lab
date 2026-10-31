# Observability: structured logs to Loki

## The contract: stderr, one JSON object per line

The process writes events to stderr and stops there (twelve-factor: treat logs as an event
stream, let the environment route it). It has no Loki client, no log file path, no shipper
settings. Here the shell redirects stderr (`2>> logs/backend.log`) and Alloy tails the
file. In ECS or Lambda the platform captures the same stream into CloudWatch Logs and the
code does not change. That portability is the point of the contract.

One JSON object per line, traceback included as an escaped string, because a collector
splits on newlines. A multi-line Python traceback would arrive as many unrelated entries.

```json
{"timestamp": "...Z", "level": "ERROR", "logger": "api.errors",
 "message": "unhandled error in GraphQL operation",
 "request_id": "9f1c...", "graphql_path": ["order"], "exception": "Traceback ..."}
```

## Where logging lives in the architecture

- Configuration (`observability/configure_logging.py`) is called only from process entry
  points: `create_app_from_environment` and the projection CLI. `create_app` itself does
  not, so tests choose their own handlers.
- Domain and application never import `observability` nor call `basicConfig`,
  `addHandler` and friends (`test_logging_architecture.py`). They stay free of an
  output concern.
- Logging happens at boundaries, where a failure is already being decided: the GraphQL error
  mapping, the consumer runner's retry or dead-letter choice, the publisher, the cache
  adapter. The relay and `CachingOrderQueries` decide in the application layer, so the
  adapters beneath them log the cause instead.
- Context ids travel in a `ContextVar` (`log_context`), not as parameters: a WSGI
  middleware binds `request_id`; the runner binds `queue`, `event_id`, `event_type`. A
  ContextVar also follows the request into the async GraphQL view and its resolver
  threads, which a thread-local would not.
- Ids only. Bodies and payloads can hold business or personal data, so no line carries
  one. A traceback can still contain an exception message; that is why the client gets
  `Internal server error` and the detail stays server-side.

## File tail versus push

| | Tail a file (Alloy) | App pushes to Loki |
| --- | --- | --- |
| Coupling | none: app writes stderr | Loki client, URL, auth inside the app |
| Loki down | logs sit in the file, shipped later | buffer in memory or drop, in the app |
| Process crash | last lines are already on disk | unsent buffer is lost |
| Cost | a file to size and rotate; position tracking in Alloy | no disk, but retry logic in app code |

Chosen: tail. The failure you most want to see is the crash, and a push buffer dies with
the process. Cost accepted: no rotation here (truncate only with Alloy stopped), and the
file holds everything, so it also contains whatever a bug logged. Alloy keeps its read
position in a volume so a restart does not re-ship the file.

## Labels versus content

Loki indexes labels, not text. Each distinct label combination is a separate stream, so a
label with many values (a request id, an event id, a client id) creates a stream per value:
a large index, many tiny chunks, slow queries. That is the cardinality problem.

- Labels here: `service`, `level`, `logger`. A handful of values each.
- Content: everything else. Find a request with `{service="backend"} |= "<request id>"` or
  `| json | request_id="..."`. Filtering content scans the matching streams' chunks, which
  is fine at lab scale and is the intended trade: cheap index, brute-force search.
- `test_loki_pipeline.py` asserts `request_id` is not a label.

## Noise control

- Expected domain outcomes (`NOT_FOUND`, `CONFLICT`) are not logged as errors: an error line
  should mean someone may need to act.
- Strawberry also logs the same exception; its logger is silenced so each incident is one
  line with one request id.
- The cache warns about Valkey failures once per five seconds, the same window as the read
  path's cooldown. Invalidations have no cooldown of their own, so the adapter throttles its
  own warning. Without that, an outage would write a line per request and bury the signal.

## What logs cannot do

- Metrics: "error rate" or "p99 latency" computed by counting log lines is slow, sampled
  or expensive. Use counters and histograms (Prometheus, CloudWatch metrics).
- Traces: a log line shows one process's view. Following one order across API, outbox,
  RabbitMQ, projection needs a trace id propagated in message headers (OpenTelemetry).
  `event_id` is a poor man's correlation key, enough for this lab.
- Absence: nothing is logged when a webhook never arrives or a worker is stuck. That needs
  alerts on rates and lag, and reconciliation (see `reconciliation.md`).
- Guarantees: stderr and a tailed file are best effort; a full disk or an unreadable file
  silently drops lines.

## Mapping to AWS (interview)

| Lab | AWS |
| --- | --- |
| JSON on stderr | same code; ECS/Fargate `awslogs` driver or Lambda sends it to CloudWatch Logs |
| Alloy tailing a file | the log driver, or the CloudWatch agent / FireLens (Fluent Bit) for files |
| Loki labels | log group and stream; CloudWatch Logs Insights fields instead of labels |
| `level`/`logger` queries | Logs Insights: `fields @timestamp, message \| filter level="ERROR"` |
| Dashboard panels | CloudWatch dashboards; metric filters turn log patterns into metrics |
| `request_id` | propagate the API Gateway or ALB request id; X-Ray for traces |

Differences to name: CloudWatch indexes JSON fields automatically (no label cardinality
decision, but you pay per ingested and scanned GB), and retention is a per-log-group setting.

## Known gaps

- Dead relay rows (`OutboxStatus.DEAD`) are decided in the application layer and are not
  logged: the publisher logs each failed attempt, and nothing announces the final giving up.
  No relay entry point exists yet to log the batch result.
- A cache payload that cannot be parsed is still a silent miss.
- No access log with status and latency per request, no metrics, no traces, no alerts.
- The `x-last-error` header on dead-lettered messages carries the exception text; it is
  broker-side, but it is not scrubbed either.
