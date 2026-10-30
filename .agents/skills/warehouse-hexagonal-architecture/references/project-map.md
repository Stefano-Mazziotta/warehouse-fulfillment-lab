# Project map and Python examples

Read paths relative to the repository root unless stated otherwise. Treat this
map as navigation, not proof that a feature exists in the current checkout.

- [Read the checked-out code first](#read-the-checked-out-code-first)
- [Follow fulfillment branches only when present](#follow-fulfillment-branches-only-when-present)
- [Prefer structural protocols](#prefer-structural-protocols-to-typescript-style-ceremony)
- [Ask questions that expose the boundary](#ask-questions-that-expose-the-boundary)

## Read the checked-out code first

Start with `AGENTS.md`, `README.md`, `roadmap.md`, `docs/domain-rules.md`, and
`docs/domain-glossary.md`. Inspect relevant `odd/tasks/` records for agreed scope
and `docs/decisions/` when present. Keep code, identifiers, and technical docs in
English.

At the master baseline used for this adaptation (`b2ccc0f`), the existing slice is:

| Role | Existing path |
| --- | --- |
| Immutable stock snapshot | `src/inventory/domain/balance.py` |
| Read use case and not-found outcome | `src/inventory/application/get_inventory.py` |
| Application-owned read protocol | `src/inventory/application/ports.py` |
| In-memory adapter | `src/inventory/adapters/in_memory.py` |
| Static dependency guard | `tests/inventory/test_architecture.py` |

Trace that read before suggesting a new layout. Do not treat file renames or an
`infrastructure` directory as prerequisites for hexagonal architecture.

## Follow fulfillment branches only when present

The local fulfillment feature chain reviewed during adaptation (#5–#17) extends
the skeleton. Re-discover these paths on that chain or after merge:

| Boundary | Representative feature-chain paths |
| --- | --- |
| Inventory ports | `src/inventory/application/inventory_repository.py`, `src/inventory/application/inventory_transaction.py` |
| Order orchestration and transaction port | `src/orders/application/allocate_order.py`, `src/orders/application/order_transaction.py` |
| Shared local write transaction | `src/orders/infrastructure/postgres_order_transaction.py` |
| Picking/packing | `src/picking/application/`, `src/packing/domain/`, `src/packing/application/` |
| Carrier boundary | `src/shipping/application/carrier_port.py`, `src/shipping/application/ship_order.py`, `src/shipping/application/reconcile_shipment.py` |
| Delivery guarantees | `src/messaging/application/`, `src/messaging/infrastructure/` |
| Channel ingestion/reconciliation | `src/integrations/application/`, `src/integrations/infrastructure/` |
| Representative EDI mapping | `src/integrations/edi/` |
| Flask factory and wiring | `src/api/app_factory.py`, `src/api/service_composition.py` |
| Inbound adapters | `src/api/graphql/`, `src/api/rest/`, relevant CLI/worker entry points |
| Derived reads | Order cache/projection ports under `src/orders/application/` and their infrastructure adapters |
| Behavioral/import checks | Corresponding capability directories under `tests/` |

Preserve the shared transaction across order, reservation, stock, package, and
outbox writes where required. Do not split transactions by capability just to
make packages look independent. Keep inner-layer ports free of SQLAlchemy types
even when one concrete adapter satisfies multiple protocols.

## Prefer structural protocols to TypeScript-style ceremony

The inventory skeleton already supplies a small read contract with this shape:

```python
from typing import Protocol

from inventory.domain import InventoryBalance, InventoryKey


class InventoryRepository(Protocol):
    def get(self, key: InventoryKey) -> InventoryBalance | None:
        ...
```

Let the application receive that contract; let adapters satisfy it structurally.
Do not add explicit inheritance, a generic `BaseRepository`, or a service
container. Reuse the existing `GetInventory` rather than generate a parallel
example implementation.

On a branch that already has write transaction ports, express a transaction
factory with standard-library types:

```python
from collections.abc import Callable
from contextlib import AbstractContextManager

from orders.application.order_transaction import OrderTransaction

TransactionFactory = Callable[[], AbstractContextManager[OrderTransaction]]
```

Treat this alias as an illustration, not a new module requirement. Construct a
fresh concrete transaction per execution in the composition root; never share a
live transaction through a global use case. Do not copy the upstream payment
example's remote-call-then-save sequence into shipping without durable
attempt/recovery semantics.

## Ask questions that expose the boundary

- Inventory: can two orders consume the last unit? Which test can prove safety?
- Picking: does a retry set a cumulative target or add an increment? Whose
  reservation changes?
- Packing: do packages account for this order's picked reservations exactly?
- Shipping: what survives a lost carrier response? Which identity is reused?
- Webhooks: what does persisted evidence mean if a redelivery changes the body?
- Messaging: what committed before acknowledgement, and what can be duplicated?
- Cache/projection: what stays authoritative during outages or reordered events?
- Flask: can transport validation use fake services while the core runs without
  the web framework?

During learning, ask one useful question at a time and wait for the learner's
reasoning before giving a complete mechanism. During review, use Problem /
Impact / Solution with evidence instead of asking the learner to investigate an
unsubstantiated concern.
