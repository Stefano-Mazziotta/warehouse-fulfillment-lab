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
        return self.on_hand - self.allocated

    def validate_invariants(self) -> None:
        for name in ("on_hand", "allocated", "picked", "packed"):
            quantity = getattr(self, name)
            if type(quantity) is not int or quantity < 0:
                raise InventoryError(f"{name} must be a nonnegative integer")
        if self.allocated > self.on_hand:
            raise InventoryError("allocated cannot exceed on_hand")
        if self.picked > self.allocated:
            raise InventoryError("picked cannot exceed allocated")

    def receive(self, quantity: int) -> "InventoryBalance":
        if type(quantity) is not int or quantity <= 0:
            raise InventoryError("received quantity must be a positive integer")
        return replace(self, on_hand=self.on_hand + quantity)

    def allocate(self, quantity: int) -> "InventoryBalance":
        if type(quantity) is not int or quantity <= 0:
            raise InventoryError("allocated quantity must be a positive integer")
        if quantity > self.available:
            raise InventoryError("allocated quantity cannot exceed available stock")
        return replace(self, allocated=self.allocated + quantity)

    def release(self, quantity: int) -> "InventoryBalance":
        if type(quantity) is not int or quantity <= 0:
            raise InventoryError("released quantity must be a positive integer")
        if quantity > self.allocated - self.picked:
            raise InventoryError("cannot release picked or unallocated stock")
        return replace(self, allocated=self.allocated - quantity)

    def pick(self, quantity: int) -> "InventoryBalance":
        if type(quantity) is not int or quantity <= 0:
            raise InventoryError("picked quantity must be a positive integer")
        if quantity > self.allocated - self.picked:
            raise InventoryError("picked cannot exceed allocated")
        return replace(self, picked=self.picked + quantity)

    def pack(self, quantity: int) -> "InventoryBalance":
        # TODO: decide whether packed belongs in this balance or in an order /
        # package model, then enforce the relevant quantity relationship.
        raise NotImplementedError

    def ship(self, quantity: int) -> "InventoryBalance":
        """Stock leaves the building; `packed` stays a legacy, non-authoritative count."""
        if type(quantity) is not int or quantity <= 0:
            raise InventoryError("shipped quantity must be a positive integer")
        if quantity > self.picked:
            raise InventoryError("cannot ship more than picked stock")
        return replace(
            self,
            on_hand=self.on_hand - quantity,
            allocated=self.allocated - quantity,
            picked=self.picked - quantity,
        )
