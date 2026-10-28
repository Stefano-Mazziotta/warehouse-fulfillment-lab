import strawberry

from orders.domain import OrderLine


@strawberry.type(name="OrderLine")
class OrderLineType:

    line_id: str
    sku: str
    quantity: int

    @classmethod
    def from_domain(cls, line: OrderLine) -> "OrderLineType":
        return cls(line_id=line.line_id, sku=line.sku, quantity=line.quantity)
