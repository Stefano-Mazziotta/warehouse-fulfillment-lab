"""Starter model for inventory balances.

This is deliberately incomplete: fill in the TODOs and be ready to explain
the consistency boundary before connecting this model to a database.
"""

from dataclasses import dataclass


@dataclass
class InventoryBalance:
    """Current quantities for one inventory scope.

    Starting assumption to challenge: a balance belongs to one client, SKU,
    warehouse, and location (for example, ``04-B-12``). If your balance is
    aggregated at a different level, change these identity fields accordingly.

    In a 3PL, ``client_id`` identifies the inventory owner/account, not the
    end customer who buys the product.
    """

    client_id: str
    sku: str
    warehouse_id: str
    location_id: str
    on_hand: int = 0
    allocated: int = 0
    picked: int = 0
    packed: int = 0

    @property
    def available(self) -> int:
        """Units this balance can promise to a new order."""
        return self.on_hand - self.allocated

    def validate_invariants(self) -> None:
        """TODO: reject an invalid balance; do not silently repair it.

        Hint: validate non-negative tracked quantities, allocated <= on_hand,
        picked <= allocated, and any additional relationship you decide for
        packed. Consider when this validation must run.
        """
        raise NotImplementedError

    def receive(self, quantity: int) -> None:
        """Record stock received into this location.

        Hint: decide whether zero is a valid request. Receiving changes
        on_hand; it should not change allocated.
        """
        raise NotImplementedError

    def allocate(self, quantity: int) -> None:
        """Reserve stock for an order.

        Hint: what must be true before increasing allocated? The check and
        update must be atomic at the persistence boundary. A FIFO queue alone
        does not guarantee this if multiple consumers can process concurrently.
        """
        raise NotImplementedError

    def pick(self, quantity: int) -> None:
        """Record units physically picked for allocated work.

        Hint: picked is a subset of allocated, so repeated partial picks must
        not let picked exceed allocated. Picking does not change available.
        """
        raise NotImplementedError

    def pack(self, quantity: int) -> None:
        """Record picked units placed into package(s)."""
        # TODO: decide whether packed belongs in this balance or in an order /
        # package model, then enforce the relevant quantity relationship.
        raise NotImplementedError

    def ship(self, quantity: int) -> None:
        """Record units leaving the warehouse on a shipment.

        Hint: on_hand and allocated decrease by the same shipped quantity, so
        available is unchanged. Decide how picked/packed quantities are cleared.
        Shipped is usually a movement/history fact, not current on-hand stock.
        """
        raise NotImplementedError
