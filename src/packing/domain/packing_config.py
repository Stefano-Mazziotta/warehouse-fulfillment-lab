from dataclasses import dataclass

from orders.domain import Order, OrderError, Reservation

from .package import Package


@dataclass(frozen=True)
class PackingConfig:

    order: Order
    reservations: tuple[Reservation, ...]
    packages: tuple[Package, ...]

    def _totals(self) -> tuple[dict, dict]:
        lines = {line.line_id: line for line in self.order.lines}
        expected = {}
        line_totals: dict[str, int] = {}
        for reservation in self.reservations:
            identity = (reservation.order_key, reservation.line_id, reservation.stock_key)
            line = lines.get(reservation.line_id)
            if (reservation.order_key != self.order.key or line is None
                    or reservation.stock_key.warehouse_id != self.order.warehouse_id
                    or reservation.stock_key.sku != line.sku or identity in expected):
                raise OrderError("Packing requires unique owned reservations")
            expected[identity] = reservation.picked_quantity
            line_totals[reservation.line_id] = line_totals.get(
                reservation.line_id,
                0,
            ) + reservation.quantity
        if line_totals != {line.line_id: line.quantity for line in self.order.lines}:
            raise OrderError("Reservations must exactly cover order lines")
        actual = {identity: 0 for identity in expected}
        package_ids = set()
        for package in self.packages:
            if package.order_key != self.order.key or package.package_id in package_ids:
                raise OrderError("Packages must be unique and owned by this order")
            package_ids.add(package.package_id)
            for item in package.contents:
                if item.identity not in expected:
                    raise OrderError("Package content has no owned reservation")
                actual[item.identity] += item.quantity
                if actual[item.identity] > expected[item.identity]:
                    raise OrderError("Packed quantity exceeds picked reservation")
        return expected, actual

    def validate(self) -> None:
        self._totals()

    def require_complete(self) -> None:
        expected, actual = self._totals()
        if actual != expected or any(r.picked_quantity != r.quantity for r in self.reservations):
            raise OrderError("Packages must exactly cover all picked reservations and order lines")
