import strawberry

from ..inventory.stock_location_input import StockLocationInput


@strawberry.input(name="RecordPickInput")
class RecordPickInput:

    order_id: str
    line_id: str
    stock: StockLocationInput
    picked_quantity: int = strawberry.field(
        description="Cumulative total picked from this reservation, not a delta, so retries are safe.")
