"""The stock identity whose quantities an inventory balance describes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class InventoryKey:
    """Provisional stock scope: owner, product, warehouse and physical location.

    The client is the inventory owner in a 3PL, not the end buyer.
    """

    client_id: str
    sku: str
    warehouse_id: str
    location_id: str
