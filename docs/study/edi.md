# EDI from the business side: four documents and one idea

Study note for `src/integrations/edi/` and `fixtures/edi/`. The lab reads and writes four
representative X12 documents so the business flows are concrete. It is **not** an EDI
implementation: no schema validation, no acknowledgements, no transport, no partner rules.
All IDs, names and tracking numbers in the fixtures are fake (`T` test indicator in ISA15).

## What EDI is, and what it is not

EDI is batch business-document exchange between companies, in agreed formats (X12 in the
US, EDIFACT elsewhere). A trading partner sends a file; you translate it into your own
model. The partner relationship, not a public API contract, defines the rules.

| | REST / GraphQL | Webhook | Queue | EDI |
|---|---|---|---|---|
| Shape | request/response | push notification of a change | internal async messages | whole documents in files |
| Who defines the contract | the API owner | the sender | you | the partner, per implementation guide |
| Delivery | synchronous result | at-least-once, may be lost | at-least-once | at-least-once, often batched |
| Dedupe handle | idempotency key | event ID | message ID | ISA control number + sender |
| Failure signal | HTTP status | none unless you poll | DLQ | functional acknowledgement (997/999) or a human email |

Transport is a separate concern and only conceptual here: a VAN (a mailbox network that
forwards between partners), AS2 (signed HTTP), or SFTP (drop a file in a folder). All of
them deliver at least once. The same file arriving twice is normal, not an incident.

## The four documents

Direction is from the sender to the receiver. "Lab" is the warehouse (3PL); "brand" is
its client, who owns the inventory; "retailer" is the brand's customer.

| | 850 Purchase Order | 940 Warehouse Shipping Order | 945 Warehouse Shipping Advice | 856 Advance Ship Notice |
|---|---|---|---|---|
| Sender to receiver | retailer to brand | brand to lab | lab to brand | brand (or lab on its behalf) to retailer |
| Why it exists | the retailer wants to buy | the brand asks the warehouse to ship it | the warehouse confirms what physically left | the retailer must plan receiving dock work |
| Business event | purchase committed | fulfillment requested | shipment completed | shipment is on its way |
| Key information | PO number, ship-to, SKU lines, quantities, prices | depositor order number, ship-to, warehouse, SKU lines, quantities | order number, shipment ID, tracking, ordered vs shipped per SKU | shipment ID, PO reference, packages with tracking, SKU and quantity per package |
| If duplicated | a second order for the same PO | a second shipment: double-shipped goods | a second "shipped" claim: inventory decremented twice downstream | a second receiving appointment |
| If it fails or is lost | no order exists, and nobody knows | the warehouse never ships; the brand waits | the brand thinks nothing shipped, may re-send or cancel | the retailer refuses or delays the delivery |
| Reconciled by | brand's order system vs retailer's PO list | open 940s with no 945 after the SLA | 945 vs the warehouse's own shipments (`reconcile_advice`) | 856 vs 945 vs retailer's receipts |

Lab mapping:

- **850 and 940 become `Order`** through `EdiOrderIntake`, which calls the existing
  `CreateOrder` use case inside the existing idempotent-consumer transaction. The sender ID
  is the `client_id` (the inventory owner), the order number is the `order_id`. A 940 names
  its warehouse; an 850 does not, so the edge supplies a default.
- **945 and 856 are projections** of an order that really shipped: `write_945` and
  `write_856` render an `Order` plus its `SHIPPED` `ShippingAttempt`. The documents are
  derived output, never the source of truth. Tests prove the output equals the sample files
  and reads back through the same reader.
- The mapper lives at the edge. `orders` and `integrations` domain/application code know
  nothing about X12, and the architecture test still enforces that.

## Duplicates: control numbers as idempotency keys

The interchange envelope carries a sender, a receiver and a control number (ISA13, echoed
in IEA02). `Interchange.idempotency_key` is `sender:control_number`. Intake records it in
the inbox in the same transaction as the order, so:

- the same file twice: second `receive` returns `False`, `CreateOrder` is never reached;
- a resend under a **new** control number for the same order: absorbed by `CreateOrder`'s
  own idempotency (same payload is a no-op);
- the same order number with **different** content under a new control number: `OrderError`,
  the transaction rolls back, nothing is overwritten, and the inbox row is not kept.

Two layers, same as the webhook-plus-reconciler design in the reconciliation note. Known
hazard: control numbers are unique per sender only if the sender never resets its counter.
A partner that restarts at 1 would be misread as a duplicate. Real systems pair the key
with a content hash or investigate gaps and repeats in the sequence.

## Failure: bad files create nothing

`read_interchange` refuses a file with no complete ISA header, no IEA trailer (the typical
signature of a truncated transfer), a mismatched control number, no transaction set, or more than one (the reader takes one
transaction per interchange and does not split batches; it also requires one matching ST/SE pair).
The extractors only ever see the segments between that ST and SE: a business segment (for
example a stray `W01`) before the ST or after the SE is refused, so data outside the declared
transaction can never change quantities. The
extractors refuse a missing order number, non-numeric or non-positive quantities, and zero
SKU lines. Parsing and mapping run **before** any transaction opens, so a rejected file
touches no state and leaves no half-applied order.

Rejecting is not the same as telling the partner. Real flows answer with a functional
acknowledgement: **997** (X12 4010) or **999** (5010) says "I received your interchange and
it was syntactically accepted or rejected", per transaction set. It is not a business
acceptance. The lab does not generate acknowledgements; a rejected file simply raises.

## Reconciliation: a 945 is a claim

`reconcile_advice(advice, attempt)` compares an advice with the shipping attempt:

| Situation | Result |
|---|---|
| No attempt, or attempt not `SHIPPED` | `NOT_SHIPPED`: surfaced, not silently accepted |
| Shipment ID differs | `SHIPMENT_ID_DIFFERS` |
| Tracking differs | `TRACKING_DIFFERS` |
| SKU totals differ | `QUANTITY_DIFFERS` |

A 945 for a partial shipment lists the unshipped SKUs with shipped quantity `0`; the reader
accepts that for advice lines (order lines still need a positive quantity) and reconciliation
treats a `0` line as "not shipped".

It only reports. What to do about a mismatch (resend, investigate, wait for the carrier
reconciliation to finish) is a business decision. Delivery of a document never proves the two
systems agree; periodic comparison of open 940s against 945s is the safety net, exactly as
polling is for webhooks.

## What the reader deliberately skips

It uses the delimiters declared in the fixed 106-character ISA header and then reads a few
segments (`BEG/PO1`, `W05/W01`, `W06/W12`, `BSN/PRF/MAN/LIN/SN1`, `N1`). It does not verify
`SE01`/`GE01`/`IEA01` counts, qualifiers beyond `SK`, repeating loops, composite elements,
dates or prices.

Why not implement compliance: it is a large, partner-specific surface (each trading partner
publishes an implementation guide that changes the rules), and it teaches little that the
business flow does not. The valuable lessons are the idempotency key, the rollback
boundary, the projection from shipped data and the reconciliation check. In production
you would use a translator or EDI provider and keep only the mapping at the edge, which is
the part this lab models.

## Known gaps

- The lab `Order` has no ship-to address or customer PO, so `write_856` takes them as
  arguments and intake ignores the 940's PO and ship-to.
- The 940 line ID is the line position; partners with real line numbers need them mapped.
- Tracking is order-level in the lab carrier, so every package in an 856 repeats it.
- Known limitation: the tenant comes from the sender id (ISA06), which is unauthenticated
  input. A real system needs a partner allow-list mapping authenticated senders to tenants.
- No cancellations (940 cancel code) or amendments, no acknowledgements, no persistence of outbound control numbers.

## Interview-ready summary

> EDI is how companies exchange business documents in agreed formats, usually by file over
> SFTP, AS2 or a VAN. For a 3PL the core flow is: the brand sends a 940 shipping order, the
> warehouse picks, packs and ships, and replies with a 945 shipping advice; the brand then
> sends the retailer an 856 advance ship notice for its 850 purchase order. Delivery is at
> least once, so I treat the ISA control number plus sender as an idempotency key and
> record it in the same transaction as the effect. I validate and map the file before
> opening a transaction so a truncated file changes nothing. The mapper sits at the edge
> and calls the same use cases as REST or GraphQL; the domain never sees X12. Because
> documents can be lost or wrong, I reconcile advices against what actually shipped
> instead of trusting delivery, and I would answer partners with 997/999 acknowledgements.
> I would not hand-write a compliant parser in production; I would use a translator and
> keep my own mapping thin.

## Interview questions

1. Who sends a 940 and who sends a 945? Why are they separate documents?
2. The same interchange arrives twice. Which key detects it and where is it stored?
3. A partner resets its control-number counter. What breaks and how would you notice?
4. A file is cut off mid-transfer. How do you know, and why must nothing be applied?
5. What does a 997 acknowledge, and what does it not?
6. A 945 says shipped but our records say packed. What do you do?
7. Why derive 945/856 from shipped data instead of storing EDI text as the record?
8. Where should X12 knowledge live in a hexagonal architecture?
