"""Database-free shipping transaction and a scriptable carrier."""
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "packing"))

from in_memory_packing_transaction import (  # noqa: E402
    InMemoryPackingTransaction, full_packages,
)
from orders.domain import OrderStatus  # noqa: E402
from shipping.application.carrier_timeout import CarrierTimeout  # noqa: E402
from shipping.application.carrier_unavailable import CarrierUnavailable  # noqa: E402
from shipping.domain.carrier_receipt import CarrierReceipt  # noqa: E402


class InMemoryShippingTransaction(InMemoryPackingTransaction):
    _state_names = (*InMemoryPackingTransaction._state_names, "attempts")

    def __init__(self, status=OrderStatus.PACKED, packages=None):
        super().__init__(status, full_packages() if packages is None else packages)
        self.attempts = {}

    def get_attempt(self, key):
        return self.attempts.get(key)

    def create_attempt(self, attempt):
        self._require_order_lock(attempt.order_key)
        if attempt.order_key in self.attempts:
            raise RuntimeError("An order has one shipping attempt")
        self.attempts[attempt.order_key] = attempt

    def save_attempt(self, attempt):
        self._require_order_lock(attempt.order_key)
        self.attempts[attempt.order_key] = attempt


class ScriptedCarrier:
    """Deduplicates by attempt ID like the CarrierPort contract demands."""

    def __init__(self, transaction):
        self._transaction = transaction
        self.shipments: dict[str, CarrierReceipt] = {}
        self.create_attempt_ids: list[str] = []
        self.find_calls = 0
        self.drop_next_create = False
        self.lose_next_create_response = False
        self.lookup_unavailable = False
        self.tamper = None
        self.on_call = None

    def create_shipment(self, attempt):
        self._enter()
        self.create_attempt_ids.append(attempt.attempt_id)
        if self.drop_next_create:
            self.drop_next_create = False
            raise CarrierTimeout("request never reached the carrier")
        receipt = self.shipments.setdefault(attempt.attempt_id, CarrierReceipt(
            attempt.order_key, attempt.attempt_id, attempt.package_ids, "TRACK-1"))
        if self.lose_next_create_response:
            self.lose_next_create_response = False
            raise CarrierTimeout("carrier acted but the response was lost")
        return self._answer(receipt)

    def find_shipment(self, order_key, attempt_id):
        self._enter()
        self.find_calls += 1
        if self.lookup_unavailable:
            raise CarrierUnavailable("carrier lookup is down")
        receipt = self.shipments.get(attempt_id)
        return None if receipt is None else self._answer(receipt)

    @property
    def calls(self):
        return self.find_calls + len(self.create_attempt_ids)

    def _enter(self):
        # The carrier is slow and unreliable: no WMS transaction may be held open for it.
        assert not self._transaction.active, "carrier called inside a WMS transaction"
        if self.on_call:
            self.on_call()

    def _answer(self, receipt):
        return receipt if self.tamper is None else self.tamper(receipt)
