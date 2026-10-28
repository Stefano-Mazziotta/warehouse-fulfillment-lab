"""Reconciliation framing for inbound shipping advice.

An advice is a claim about the physical world. The WMS shipping attempt is the record of
what it actually did, so a claim without a SHIPPED attempt, or one that disagrees with it,
is reported for a human or a job to resolve. Nothing here mutates state.
"""
from dataclasses import dataclass
from enum import StrEnum

from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_attempt import ShippingAttempt

from .documents import ShipAdvice


class MismatchCode(StrEnum):
    NOT_SHIPPED = "NOT_SHIPPED"
    SHIPMENT_ID_DIFFERS = "SHIPMENT_ID_DIFFERS"
    TRACKING_DIFFERS = "TRACKING_DIFFERS"
    QUANTITY_DIFFERS = "QUANTITY_DIFFERS"


@dataclass(frozen=True)
class AdviceMismatch:
    code: MismatchCode
    detail: str


def reconcile_advice(advice: ShipAdvice, attempt: ShippingAttempt | None) -> tuple[AdviceMismatch, ...]:
    if attempt is None or attempt.status != ShipmentStatus.SHIPPED:
        # Stop here: comparing details against an attempt that never shipped is noise.
        return (AdviceMismatch(
            MismatchCode.NOT_SHIPPED,
            f"Advice claims order {advice.order_number} shipped, but no SHIPPED attempt exists",
        ),)
    mismatches = []
    if advice.shipment_id != attempt.attempt_id:
        mismatches.append(AdviceMismatch(
            MismatchCode.SHIPMENT_ID_DIFFERS,
            f"advice {advice.shipment_id} vs attempt {attempt.attempt_id}"))
    if set(advice.tracking_numbers) != {attempt.tracking_number}:
        mismatches.append(AdviceMismatch(
            MismatchCode.TRACKING_DIFFERS,
            f"advice {advice.tracking_numbers} vs attempt {attempt.tracking_number}"))
    claimed: dict[str, int] = {}
    for line in advice.lines:
        claimed[line.sku] = claimed.get(line.sku, 0) + line.quantity
    actual: dict[str, int] = {}
    for key, quantity in attempt.shipped_quantities().items():
        actual[key.sku] = actual.get(key.sku, 0) + quantity
    if claimed != actual:
        mismatches.append(AdviceMismatch(
            MismatchCode.QUANTITY_DIFFERS, f"advice {claimed} vs shipped {actual}"))
    return tuple(mismatches)
