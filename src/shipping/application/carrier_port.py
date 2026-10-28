from typing import Protocol

from orders.domain import OrderKey
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipping_attempt import ShippingAttempt


class CarrierPort(Protocol):
    """Adapters raise CarrierUnavailable (or CarrierTimeout) when the outcome is unknown.

    `create_shipment` MUST be idempotent per `attempt.attempt_id`: repeating it
    returns the original receipt and never books a second shipment. Reconciliation
    relies on this to retry creation after an authoritative NOT_FOUND. Real carriers
    do not all promise this; such an adapter must supply its own deduplication.
    `find_shipment` returns None only for an authoritative NOT_FOUND, never for
    an error or an ambiguous answer.
    """

    def create_shipment(self, attempt: ShippingAttempt) -> CarrierReceipt: ...
    def find_shipment(self, order_key: OrderKey, attempt_id: str) -> CarrierReceipt | None: ...
