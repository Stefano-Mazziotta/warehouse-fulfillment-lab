# Reserve inventory without moving it

Allocation promises available units to an order. It does not move physical stock:
`on_hand` stays unchanged, `allocated` increases, and `available` decreases.

## Trace one reservation

1. Start with `on_hand=5`, `allocated=2`: three units are available.
2. Call `balance.allocate(2)` and use the returned snapshot.
3. Verify `on_hand=5`, `allocated=4`, `available=1`; the original is unchanged.
4. Run `uv run pytest tests/inventory/test_domain.py` to inspect the domain proofs.

## Rules and boundaries

| Concern | Current guarantee |
|---|---|
| Quantity | A positive exact integer; booleans, zero and fractional values are rejected. |
| Capacity | A reservation cannot exceed this snapshot's available stock. |
| Preservation | Identity, on-hand, picked and packed quantities remain unchanged. |
| Repeated allocation | Each call on the latest returned snapshot uses its remaining capacity. |
| Failure | Invalid requests raise `InventoryError` without changing the original. |

These are domain invariants, not a persistence guarantee. The frozen dataclass
prevents mutation of one object; it does not serialize workers or save anything.
Two workers can each read the same last available unit and independently produce
valid snapshots. Persistence must protect the check and update together; the
concurrency proof belongs to the next slice, not these unit tests.

Picking, packing and shipping remain unimplemented. The existing balance-wide
`packed` counter is a template placeholder, not a package model.

## Challenge your reasoning

1. Why does allocating two units reduce available stock without reducing on-hand?
2. What happens if you allocate twice from the original snapshot instead of using the returned one?
3. If two workers each allocate the same last unit successfully in memory, what has the domain test not proved?

## Next step

Explain the last-unit race before inspecting the persistence implementation.
