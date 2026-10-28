from collections.abc import Sequence

from sqlalchemy import Engine, select

from shipping.application.attempt_summary import AttemptSummary
from shipping.domain.shipment_status import ShipmentStatus

from .shipping_schema import shipping_attempt_packages, shipping_attempts


class PostgresAttemptQueries:

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def attempts_for(
        self, client_id: str, order_ids: Sequence[str]
    ) -> dict[str, AttemptSummary]:
        attempts = select(shipping_attempts).where(
            shipping_attempts.c.client_id == client_id,
            shipping_attempts.c.order_id.in_(order_ids),
        )
        included = (
            select(shipping_attempt_packages.c.order_id, shipping_attempt_packages.c.package_id)
            .where(
                shipping_attempt_packages.c.client_id == client_id,
                shipping_attempt_packages.c.order_id.in_(order_ids),
            )
            .order_by(shipping_attempt_packages.c.order_id, shipping_attempt_packages.c.package_id)
        )
        with self._engine.connect() as connection:
            attempt_rows = connection.execute(attempts).mappings().all()
            package_rows = connection.execute(included).all()
        package_ids: dict[str, list[str]] = {}
        for order_id, package_id in package_rows:
            package_ids.setdefault(order_id, []).append(package_id)
        return {
            row["order_id"]: AttemptSummary(
                row["order_id"], row["attempt_id"], ShipmentStatus(row["status"]),
                row["tracking_number"], tuple(package_ids.get(row["order_id"], ())),
            )
            for row in attempt_rows
        }
