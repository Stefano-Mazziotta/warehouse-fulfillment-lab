# Warehouse & Logistics Backend — Interview Practice Roadmap

## 🎯 Goal

Build a small warehouse fulfillment platform inspired by a real WMS such as ShipHero.

The goal is **not** to reproduce ShipHero.

The goal is to learn the business domain while practicing:

* Python
* Flask
* GraphQL
* PostgreSQL
* Redis
* DDD
* Hexagonal Architecture
* Screaming Architecture
* Vertical Slicing
* Concurrency
* Async processing
* Webhooks
* EDI
* External integrations
* AWS
* Observability

The project should gradually evolve from a simple order system into a
small **order-to-shipment workflow**.

---

## Phase 1 — Understand the Warehouse Business

Before writing code, understand the lifecycle of a physical order.

```text
Customer
   ↓
Sales Channel
   ↓
Order
   ↓
Inventory Allocation
   ↓
Picking
   ↓
Packing
   ↓
Shipping
   ↓
Carrier
   ↓
Tracking
   ↓
Customer
```

### Concepts to Learn

#### Commerce

* Sales Channel
* Store
* Customer
* Order
* Order Item
* Product
* SKU
* Variant

#### Warehouse

* Warehouse
* Location / Bin
* Inventory
* On-hand Inventory
* Allocated Inventory
* Available Inventory
* Pickable Inventory
* Sellable / Non-sellable Inventory
* Stock Movement

#### Fulfillment

* Allocation
* Picking
* Pick List
* Pick Batch / Wave
* Tote
* Packing
* Package
* Shipment
* Carrier
* Tracking Number
* Shipping Label
* Shipping Service
* Return

#### 3PL

Understand what changes when the warehouse is operated for another company.

```text
WMS
 │
 ├── 3PL
 │    ├── Client A
 │    ├── Client B
 │    └── Client C
 │
 └── Brand
```

Questions:

* Who owns the inventory?
* Who owns the order?
* Who pays for fulfillment?
* How is inventory isolated?
* How is fulfillment billed?
* Can two clients have the same SKU?
* Can one client have multiple warehouses?

### Deliverable

Create:

```text
/docs/domain-glossary.md
```

Document the terminology in your own words.

**Goal:** Be able to explain the warehouse business without mentioning
Python or architecture.

---

## Phase 2 — Inventory Management

Focus entirely on inventory.

Start with:

```text
Product
   ↓
SKU
   ↓
Warehouse
   ↓
Location
   ↓
Inventory
```

### Learn the Difference Between

```text
On Hand
Allocated
Available
Picked
Packed
Shipped
```

Understand the relationship between them.

For example:

```text
Available = On Hand - Allocated
```

But verify the actual business meaning while researching.

### Inventory Movements

Understand what happens when:

```text
Purchase arrives
      ↓
Inventory increases
```

```text
Order created
      ↓
Inventory allocated
```

```text
Picker picks item
      ↓
Inventory changes
```

```text
Order shipped
      ↓
Inventory leaves warehouse
```

For each operation ask:

* Is this a state change?
* Is this a movement?
* Is this an event?
* Should it be transactional?

### Deliverable

Create your inventory domain model.

Document the invariants you believe must always be true.

Example:

```text
Allocated inventory cannot exceed available inventory.
```

Don't stop at one invariant. Find the others.

---

## Phase 3 — Inventory Allocation & Concurrency

Implement your first serious backend problem.

Scenario:

```text
SKU-123

Available: 1
```

Two orders arrive simultaneously:

```text
Order A → wants 1
Order B → wants 1
```

Only one order should successfully allocate the inventory.

### Research

Learn:

* Database transactions
* Row-level locking
* `SELECT ... FOR UPDATE`
* Optimistic locking
* Isolation levels
* Race conditions
* Deadlocks
* Transaction boundaries

### Exercise

Create a test that intentionally produces concurrent allocation attempts.

```text
Order A ───────┐
               ├──> Inventory Allocation
Order B ───────┘
```

Verify that the inventory invariant is preserved.

### Deliverable

A concurrency test proving that your system cannot oversell inventory.

---

## Phase 4 — Order Domain & State Machine

Introduce DDD.

Investigate:

* Entities
* Value Objects
* Aggregates
* Aggregate boundaries
* Domain invariants
* Domain Services

Possible entities:

```text
Order
OrderItem
Inventory
Warehouse
Package
Shipment
```

Don't automatically make everything an aggregate.

Ask:

> Where does business consistency actually matter?

### Order Lifecycle

Research real warehouse order states.

Start with:

```text
CREATED
   ↓
ALLOCATED
   ↓
PICKING
   ↓
PICKED
   ↓
PACKED
   ↓
SHIPPED
```

Then investigate:

* Cancellation
* Backorders
* Partial fulfillment
* Partial picking
* Failed shipment
* Returns

### Deliverable

Document your order state machine before implementing it.

---

## Phase 5 — Picking

Now learn what physically happens inside a warehouse.

Research:

* Pick List
* Pick Wave
* Batch Picking
* Single-order Picking
* Zone Picking
* Pick Path
* Tote
* Scanner
* Pick Station
* Short Pick

Think about:

> If an order contains 20 items, how does a warehouse worker actually
> receive and execute that work?

Model a simplified picking workflow.

Don't build a sophisticated optimization algorithm.

Focus on understanding the business process.

---

## Phase 6 — Packing

Now investigate how orders become physical packages.

Understand the difference between:

```text
Order
```

and:

```text
Packages
```

One order can become:

```text
Order #123
   │
   ├── Package 1
   │     ├── Item A × 2
   │     └── Item B × 1
   │
   └── Package 2
         └── Item C × 4
```

### Research Package Attributes

* Weight
* Dimensions
* Packaging Type
* Items
* Quantity
* Shipping Label
* Tracking
* Carrier
* Shipping Service

### Exercise

Design a `PackingConfig`.

Ask:

> What invariants must a packing configuration satisfy?

For example:

```text
Every packed quantity must correspond to an order item.
```

Find the remaining rules yourself.

---

## Phase 7 — Shipping Domain

Learn the terminology:

```text
Carrier
Shipping Service
Shipping Method
Shipment
Tracking Number
Shipping Label
Rate
```

Research how these concepts differ.

Examples of carriers:

```text
UPS
FedEx
USPS
DHL
```

### Architecture Exercise

Define a shipping port/interface.

Your application should depend on something conceptually like:

```text
ShippingService
```

rather than directly depending on:

```text
UPS API
FedEx API
```

Then create fake implementations.

```text
Application
     ↓
ShippingService
     ↓
 ┌───┴────┐
 ↓        ↓
UPS     FedEx
Adapter Adapter
```

### Deliverable

Switching from UPS to FedEx should not require changing the order
fulfillment use case.

---

## Phase 8 — EDI

Now move from internal warehouse operations to B2B logistics communication.

### Learn

> EDI = Electronic Data Interchange

Research common logistics transaction sets.

#### EDI 850

Purchase Order.

```text
Buyer
  │
  │ EDI 850
  ▼
Supplier / Warehouse
```

#### EDI 940

Warehouse Shipping Order.

Conceptually:

```text
Client
   │
   │ "Ship these items"
   ▼
3PL / Warehouse
```

#### EDI 945

Warehouse Shipping Advice.

Conceptually:

```text
Warehouse
   │
   │ "This is what we actually shipped"
   ▼
Client
```

Also research:

* EDI 856 — Advance Ship Notice
* EDI 810 — Invoice
* EDI 846 — Inventory Inquiry / Advice

### Exercise

Don't implement everything.

Choose:

* One inbound EDI flow
* One outbound EDI flow

Understand their lifecycle.

---

## Phase 9 — API vs Webhook vs EDI vs Queue

Compare:

```text
REST API
GraphQL
Webhook
EDI
Message Queue
```

For each one understand:

* Who initiates communication?
* Synchronous or asynchronous?
* What happens if delivery fails?
* How do you retry?
* How do you detect duplicates?
* How do you reconcile missing messages?
* How do you version the contract?
* Who owns the source of truth?

### Deliverable

Create:

```text
/docs/integrations.md
```

Document your conclusions.

---

## Phase 10 — External Integration

Implement a simplified sales-channel integration.

For example:

```text
Shopify
   ↓
Webhook
   ↓
Flask
   ↓
Queue
   ↓
Order Processor
   ↓
WMS
```

The webhook endpoint should not execute the entire workflow synchronously.

Think:

```text
Webhook
   ↓
Validate
   ↓
Persist Event
   ↓
Enqueue
   ↓
Return 200
```

Then:

```text
Worker
   ↓
Process Event
   ↓
Update Domain
```

---

## Phase 11 — Idempotency

Now deliberately send the same event twice.

```text
OrderCreated
event_id = abc123
```

Then:

```text
OrderCreated
event_id = abc123
```

Your system must not create two orders.

### Research

* Idempotency Keys
* Unique Constraints
* Processed Events
* At-least-once Delivery
* Exactly-once Semantics
* Retry Semantics

Then implement your own strategy.

---

## Phase 12 — Reconciliation

Assume your webhook system failed.

```text
Shopify
   │
   │ Order updated
   X
   │
   ▼
Your WMS
```

The WMS never received the event.

How can you discover the missing update?

### Research

* Reconciliation Jobs
* `updated_at`
* Cursor-based Synchronization
* Periodic Polling
* Checkpoints
* Sync Windows

### Exercise

Implement a simple reconciliation process.

The goal is to understand:

> Webhooks are notifications, not necessarily the source of truth.

---

## Phase 13 — GraphQL

Now make GraphQL your main API.

Model the API around the business domain.

### Queries

```graphql
orders
order
inventory
warehouse
shipment
```

### Mutations

```graphql
createOrder
allocateInventory
startPicking
completePicking
createPacking
shipOrder
```

Avoid exposing low-level mutations when a business operation exists.

Instead of thinking:

```graphql
updateOrderStatus
updateInventoryQuantity
```

think:

```graphql
allocateInventory
startPicking
shipOrder
```

The API should express the **business language**.

---

## Phase 14 — GraphQL Performance

Intentionally create an N+1 problem.

Example:

```graphql
orders {
    id
    items {
        product {
            warehouse {
                ...
            }
        }
    }
}
```

Research:

* N+1
* DataLoader
* Batching
* Caching
* Pagination
* Query Complexity
* Query Depth
* Rate Limiting

Then fix the problem.

---

## Phase 15 — Architecture Refactoring

Once the system works, evaluate the architecture.

The repository should scream:

```text
orders/
inventory/
warehouses/
fulfillment/
shipping/
integrations/
```

rather than:

```text
controllers/
services/
repositories/
models/
utils/
```

### Target Structure

```text
src/

orders/
    domain/
    application/
    adapters/

inventory/
    domain/
    application/
    adapters/

warehouses/
    domain/
    application/
    adapters/

fulfillment/
    domain/
    application/
    adapters/

shipping/
    domain/
    application/
    adapters/

integrations/
    shopify/
    edi/

shared/
    infrastructure/
```

### Architectural Rules

#### DDD

Business concepts live in the domain.

#### Hexagonal Architecture

External technologies depend on your application/domain, not the other way around.

#### Screaming Architecture

The project structure should communicate the business capabilities.

#### Vertical Slicing

Each business capability should contain the pieces required to implement that capability.

---

## Phase 16 — AWS

Map your architecture to AWS.

Research:

```text
Flask
PostgreSQL
Redis
Queue
Workers
Object Storage
Events
Observability
Secrets
```

Investigate:

* SQS
* Lambda
* ECS
* RDS
* S3
* EventBridge
* CloudWatch
* IAM

Don't deploy everything.

Instead, create an architecture diagram explaining:

> Why would I use this AWS service here?

---

## Phase 17 — Observability & Failures

Introduce production failure scenarios.

Simulate:

```text
Carrier API timeout
Database timeout
Duplicate webhook
Queue retry
Malformed EDI
Inventory deadlock
Unknown SKU
Warehouse unavailable
Worker crash
External API succeeds but response is lost
```

Research:

* Structured Logging
* Correlation IDs
* Metrics
* Distributed Tracing
* Sentry
* Dead Letter Queues
* Retry Policies
* Exponential Backoff

Main question:

> If an order fails somewhere in the fulfillment pipeline, can an engineer
> understand exactly what happened?

---

## Phase 18 — Final System Design

Design the complete system without coding.

Scenario:

> A Shopify order is created for a 3PL client. The order contains products
> stored across three warehouses. The system must allocate inventory, create
> picking work, allow the warehouse to pack the order into multiple packages,
> obtain shipping labels from a carrier, update tracking information, and
> notify the sales channel.

Architecture:

```text
Shopify
   │
   ▼
Webhook / API
   │
   ▼
Order Ingestion
   │
   ▼
Order
   │
   ▼
Inventory Allocation
   │
   ├── Warehouse A
   ├── Warehouse B
   └── Warehouse C
   │
   ▼
Picking
   │
   ▼
PackingConfig
   │
   ├── Package 1
   └── Package 2
   │
   ▼
ShippingService
   │
   ├── UPS
   └── FedEx
   │
   ▼
Shipment
   │
   ▼
Tracking
   │
   ▼
Shopify
```

Then introduce failures.

Ask yourself:

```text
What if the webhook is duplicated?

What if inventory allocation happens concurrently?

What if UPS times out?

What if the worker crashes?

What if the shipment succeeds but the response is lost?

What if Shopify never receives the shipment update?

What if the WMS inventory differs from the physical inventory?

What if an EDI document arrives twice?

What if two warehouses try to fulfill the same order?

What if one package ships and another package fails?
```

---

## Recommended Learning Order

```text
1. Warehouse Domain
        ↓
2. Inventory
        ↓
3. Inventory Allocation
        ↓
4. Concurrency
        ↓
5. Orders & State Machines
        ↓
6. Picking
        ↓
7. Packing
        ↓
8. Shipping
        ↓
9. Carriers
        ↓
10. APIs & Webhooks
        ↓
11. EDI
        ↓
12. Queues
        ↓
13. Idempotency
        ↓
14. Reconciliation
        ↓
15. GraphQL
        ↓
16. GraphQL Performance
        ↓
17. AWS
        ↓
18. Observability
        ↓
19. System Design
```

## The 5 Questions to Ask for Every Feature

For every business capability, ask:

```text
1. What is the business rule?

2. What is the consistency boundary?

3. What can happen concurrently?

4. What happens when an external system fails?

5. How do we know the systems are eventually consistent?
```

If you can answer those five questions for:

* Inventory Allocation
* Picking
* Packing
* Shipping
* Webhooks
* EDI
* Returns

you are no longer just practicing Flask.

You are practicing the **backend problems of a real warehouse and logistics platform**.
