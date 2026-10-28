import json

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from orders.domain import OrderKey
from shipping.application.carrier_timeout import CarrierTimeout
from shipping.application.carrier_unavailable import CarrierUnavailable
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipping_attempt import ShippingAttempt
from shipping.domain.shipping_error import ShippingError

from .fake_carrier_schema import carrier_metadata, fake_carrier_shipments


class PostgresFakeCarrier:
    """Lab stand-in for a carrier that deduplicates by attempt ID and persists durably.

    Every call uses its own committed SQL transaction, so a WMS rollback or a new
    adapter instance never changes what the "carrier" remembers. Fault flags script
    the three failure shapes a real network produces.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self.drop_next_create = False
        self.lose_next_create_response = False
        self.lookup_unavailable = False
        self.create_calls = 0

    @staticmethod
    def install(engine: Engine) -> None:
        carrier_metadata.create_all(engine)

    def create_shipment(self, attempt: ShippingAttempt) -> CarrierReceipt:
        self.create_calls += 1
        if self.drop_next_create:
            self.drop_next_create = False
            raise CarrierTimeout("request never reached the carrier")
        package_ids = json.dumps(sorted(attempt.package_ids))
        with self._engine.begin() as connection:
            connection.execute(
                postgres_insert(fake_carrier_shipments).values(
                    attempt_id=attempt.attempt_id,
                    client_id=attempt.order_key.client_id,
                    order_id=attempt.order_key.order_id,
                    package_ids=package_ids,
                    tracking_number="FAKE-" + attempt.attempt_id[:8],
                ).on_conflict_do_nothing(index_elements=["attempt_id"]))
            row = connection.execute(select(fake_carrier_shipments).where(
                fake_carrier_shipments.c.attempt_id == attempt.attempt_id)).one()
        if (row.client_id, row.order_id, row.package_ids) != (
                attempt.order_key.client_id, attempt.order_key.order_id, package_ids):
            raise ShippingError("Attempt ID already used for a different shipment payload")
        if self.lose_next_create_response:
            self.lose_next_create_response = False
            raise CarrierTimeout("carrier acted but the response was lost")
        return self._receipt(row)

    def find_shipment(self, order_key: OrderKey, attempt_id: str) -> CarrierReceipt | None:
        if self.lookup_unavailable:
            raise CarrierUnavailable("carrier lookup is down")
        with self._engine.connect() as connection:
            row = connection.execute(select(fake_carrier_shipments).where(
                fake_carrier_shipments.c.attempt_id == attempt_id)).first()
        return None if row is None else self._receipt(row)

    @staticmethod
    def _receipt(row) -> CarrierReceipt:
        return CarrierReceipt(
            OrderKey(row.client_id, row.order_id), row.attempt_id,
            frozenset(json.loads(row.package_ids)), row.tracking_number)
