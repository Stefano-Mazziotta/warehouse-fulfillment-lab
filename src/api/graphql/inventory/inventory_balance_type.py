import strawberry

from inventory.domain import InventoryBalance


@strawberry.type(name="InventoryBalance")
class InventoryBalanceType:

    sku: str
    warehouse_id: str
    location_id: str
    on_hand: int
    allocated: int
    picked: int
    available: int

    @classmethod
    def from_domain(cls, balance: InventoryBalance) -> "InventoryBalanceType":
        key = balance.key
        return cls(
            sku=key.sku, warehouse_id=key.warehouse_id, location_id=key.location_id,
            on_hand=balance.on_hand, allocated=balance.allocated, picked=balance.picked,
            available=balance.available)
