# Sales channel webhook contract

`POST /webhooks/sales-channel` is the only inbound REST endpoint. `docs/api/schema.graphql`
cannot describe it, so this file is the contract. The example below is
`sales-channel-webhook.example.json`; `tests/api/test_webhook_contract.py` posts it through
the real route and fails if this document and the parser drift apart.

> **Trust boundary:** the lab does not authenticate the sender (no signature, no token).
> Anyone who can reach the port can post events. A real deployment verifies a signature at
> the edge before parsing.

## Request

`Content-Type: application/json`, body at most 1,000,000 bytes (`max_request_bytes`).

| Field | Type | Rule |
| --- | --- | --- |
| `event_id` | string | Nonempty. Unique per sender event; the idempotency key. |
| `order.client_id` | string | Nonempty. The owner (tenant) of the order. |
| `order.channel_order_id` | string | Nonempty. The channel's own order ID. |
| `order.warehouse_id` | string | Nonempty. |
| `order.version` | integer | At least 1. The channel's counter for this order; it only grows. |
| `order.updated_at` | string | ISO 8601 **with** a timezone offset. |
| `order.lines` | array | At least one line; `line_id` unique within the order. |
| `order.lines[].line_id` | string | Nonempty. |
| `order.lines[].sku` | string | Nonempty. |
| `order.lines[].quantity` | integer | At least 1. |

```json
{
  "event_id": "evt-1001",
  "order": {
    "client_id": "acme",
    "channel_order_id": "SO-1001",
    "warehouse_id": "w1",
    "version": 1,
    "updated_at": "2026-10-01T12:00:00+00:00",
    "lines": [{"line_id": "l1", "sku": "SKU-123", "quantity": 2}]
  }
}
```

## Responses

| Status | Body | Meaning | Sender should |
| --- | --- | --- | --- |
| 202 | `{"eventId": "evt-1001", "outcome": "CREATED"}` | Event stored and the order was created. | Stop retrying. |
| 202 | `{"eventId": "evt-1001", "outcome": "DUPLICATE_EVENT"}` | This `event_id` was already processed. | Stop retrying. |
| 202 | `{"eventId": "evt-1002", "outcome": "CONFLICT"}` | Stored as evidence, **not applied**: same order and version with different content. | Do **not** treat as success; fix the data and send a higher `version`. |
| 400 | `{"error": "<reason>"}` | Invalid JSON or invalid fields. | Fix the payload; retrying the same body never succeeds. |
| 413 | `{"error": {"code": "PAYLOAD_TOO_LARGE", ...}}` | Body over the limit. | Send a smaller body. |
| 500 | `{"error": {"code": "INTERNAL", "message": "Internal server error", "requestId": "..."}}` | A dependency failed (for example the database). | Retry with the **same** `event_id` and backoff. |

Other `outcome` values on a 202: `ALREADY_KNOWN` (same version and content already stored)
and `STALE_IGNORED` (lower `version` than the stored one). A 202 means "received and
handled by policy", not "business success": always read `outcome`.

## Retry and idempotency policy

- Delivery is at-least-once. Retry 500s and network errors with the same `event_id`.
- The raw event is persisted before processing, so a retry after a failed first attempt is
  safe. Treat `event_id` as globally unique for this endpoint: the lab does not yet scope
  it per sender or tenant.
- Never reuse an `event_id` for a different payload.
- Events can arrive out of order; `version` decides which one wins, not arrival time.
