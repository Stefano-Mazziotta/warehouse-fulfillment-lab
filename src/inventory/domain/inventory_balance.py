"""Stock quantities and the rules that keep a balance valid.

Allocation, picking, packing, and shipping remain learning exercises. Define
the consistency boundary before connecting this model to a database.
"""

from dataclasses import dataclass, replace

from .inventory_error import InventoryError
from .inventory_key import InventoryKey


@dataclass(frozen=True)
class InventoryBalance:
    """Immutable snapshot, not a concurrency-safe persistence mechanism.

    Operations return new snapshots rather than mutating this balance.

    Packed is retained from the learning template as a nonnegative count only.
    Its relationship to picked and its eventual consistency boundary remain an
    explicit modeling exercise; this is not a complete packing model.
    """

    key: InventoryKey
    on_hand: int = 0
    allocated: int = 0
    picked: int = 0
    packed: int = 0

    def __post_init__(self) -> None:
        self.validate_invariants()

    @property
    def available(self) -> int:
        """Units this balance can promise to a new order."""
        return self.on_hand - self.allocated

    def validate_invariants(self) -> None:
        """Reject invalid snapshots rather than silently repairing them."""
        for name in ("on_hand", "allocated", "picked", "packed"):
            quantity = getattr(self, name)
            if type(quantity) is not int or quantity < 0:
                raise InventoryError(f"{name} must be a nonnegative integer")
        if self.allocated > self.on_hand:
            raise InventoryError("allocated cannot exceed on_hand")
        if self.picked > self.allocated:
            raise InventoryError("picked cannot exceed allocated")

    def receive(self, quantity: int) -> "InventoryBalance":
        """Return a new snapshot with received stock; reservations stay intact."""
        if type(quantity) is not int or quantity <= 0:
            raise InventoryError("received quantity must be a positive integer")
        return replace(self, on_hand=self.on_hand + quantity)

    def allocate(self, quantity: int) -> "InventoryBalance":
        """Reserve stock for an order.

        Hint: what must be true before increasing allocated? The check and
        update must be atomic at the persistence boundary. A FIFO queue alone
        does not guarantee this if multiple consumers can process concurrently.
        """
        raise NotImplementedError

    def pick(self, quantity: int) -> "InventoryBalance":
        """Record units physically picked for allocated work.

        Hint: picked is a subset of allocated, so repeated partial picks must
        not let picked exceed allocated. Picking does not change available.
        """
        raise NotImplementedError

    def pack(self, quantity: int) -> "InventoryBalance":
        """Record picked units placed into package(s)."""
        # TODO: decide whether packed belongs in this balance or in an order /
        # package model, then enforce the relevant quantity relationship.
        raise NotImplementedError

    def ship(self, quantity: int) -> "InventoryBalance":
        """Record units leaving the warehouse on a shipment.

        Hint: on_hand and allocated decrease by the same shipped quantity, so
        available is unchanged. Decide how picked/packed quantities are cleared.
        Shipped is usually a movement/history fact, not current on-hand stock.
        """
        raise NotImplementedError
