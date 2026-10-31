import strawberry

from orders.domain import Reservation


@strawberry.type(name="Reservation", description="Stock held for one order line at one location.")
class ReservationType:

    line_id: str
    sku: str
    warehouse_id: str
    location_id: str
    quantity: int
    picked_quantity: int

    @classmethod
    def from_domain(cls, reservation: Reservation) -> "ReservationType":
        stock = reservation.stock_key
        return cls(
            line_id=reservation.line_id, sku=stock.sku, warehouse_id=stock.warehouse_id,
            location_id=stock.location_id, quantity=reservation.quantity,
            picked_quantity=reservation.picked_quantity)
