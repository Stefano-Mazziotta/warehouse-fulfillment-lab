"""Derive a 945 or 856 from the data of an order that really shipped.

The documents are a projection of WMS state, never a source of it: the order and the
SHIPPED attempt exist first, the EDI text is rendered from them. Control numbers are
supplied by the caller; a real sender persists a counter so a resend is a new interchange.
"""
from datetime import datetime

from orders.domain import Order
from shipping.domain.shipment_status import ShipmentStatus
from shipping.domain.shipping_attempt import ShippingAttempt

from .x12 import EdiError

UNIT = "EA"
ISA_ID_WIDTH = 15
# Element separator, segment terminator, component separator and line breaks: a data value
# containing one would add segments or shift fields, so it is rejected, not escaped.
RESERVED = ("*", "~", ">", "\n", "\r")


def _require_plain(**elements: str) -> None:
    for name, value in elements.items():
        if any(character in str(value) for character in RESERVED):
            raise EdiError(f"{name} contains a reserved X12 delimiter: {value!r}")


def _envelope(sender: str, receiver: str, control_number: int, group: str, transaction_set: str,
              sent_at: datetime, body: list[str]) -> str:
    for role, identifier in (("sender", sender), ("receiver", receiver)):
        # ISA06/ISA08 are fixed at 15 characters; padding cannot shrink a longer id.
        if len(identifier) > ISA_ID_WIDTH:
            raise EdiError(f"ISA {role} id {identifier!r} is longer than {ISA_ID_WIDTH} characters")
    date, time = sent_at.strftime("%Y%m%d"), sent_at.strftime("%H%M")
    isa = (
        "ISA*00*" + " " * 10 + "*00*" + " " * 10
        + f"*ZZ*{sender:<15}*ZZ*{receiver:<15}*{date[2:]}*{time}*U*00401*{control_number:09d}*0*T*>~"
    )
    # SE01 counts the segments from ST to SE inclusive; we write it but never verify it on read.
    transaction = [f"ST*{transaction_set}*0001", *body]
    transaction.append(f"SE*{len(transaction) + 1}*0001")
    rows = [isa, f"GS*{group}*{sender}*{receiver}*{date}*{time}*{control_number}*X*004010~"]
    rows += [segment + "~" for segment in transaction]
    rows += [f"GE*1*{control_number}~", f"IEA*1*{control_number:09d}~"]
    return "\n".join(rows) + "\n"


def _require_shipped(attempt: ShippingAttempt) -> None:
    if attempt.status != ShipmentStatus.SHIPPED:
        raise EdiError("Advice can only be written for a SHIPPED attempt")


def _by_sku(pairs) -> dict[str, int]:
    totals: dict[str, int] = {}
    for sku, quantity in pairs:
        totals[sku] = totals.get(sku, 0) + quantity
    return dict(sorted(totals.items()))


def write_945(order: Order, attempt: ShippingAttempt, *, sender: str, receiver: str,
              control_number: int, sent_at: datetime) -> str:
    _require_shipped(attempt)
    _require_plain(sender=sender, receiver=receiver, order_id=order.key.order_id,
                   attempt_id=attempt.attempt_id, tracking_number=attempt.tracking_number,
                   **{f"sku[{n}]": line.sku for n, line in enumerate(order.lines)})
    ordered = _by_sku((line.sku, line.quantity) for line in order.lines)
    shipped = _by_sku((key.sku, quantity) for key, quantity in attempt.shipped_quantities().items())
    body = [
        f"W06*F*{order.key.order_id}*{sent_at:%Y%m%d}*{attempt.attempt_id}",
        f"MAN*CP*{attempt.tracking_number}",
    ]
    for sku, quantity in ordered.items():
        sent = shipped.get(sku, 0)
        body.append(f"W12*CC*{quantity}*{sent}*{quantity - sent}*{UNIT}**SK*{sku}")
    body.append(f"W03*{sum(shipped.values())}")
    return _envelope(sender, receiver, control_number, "SW", "945", sent_at, body)


def write_856(order: Order, attempt: ShippingAttempt, *, ship_to: str, customer_po: str, sender: str,
              receiver: str, control_number: int, sent_at: datetime) -> str:
    # The lab order has no address or customer PO yet, so the edge supplies both.
    _require_shipped(attempt)
    _require_plain(sender=sender, receiver=receiver, ship_to=ship_to, customer_po=customer_po,
                   attempt_id=attempt.attempt_id, tracking_number=attempt.tracking_number,
                   **{f"sku[{n}]": item.stock_key.sku for n, item in enumerate(
                       item for package in attempt.packages for item in package.contents)})
    body = [
        f"BSN*00*{attempt.attempt_id}*{sent_at:%Y%m%d}*{sent_at:%H%M}",
        "HL*1**S", "HL*2*1*O", f"PRF*{customer_po}", f"N1*ST*{ship_to}",
    ]
    hierarchy = 2
    for package in attempt.packages:
        # The lab's carrier returns one tracking number per order, so each package repeats it.
        body += [f"HL*{hierarchy + 1}*2*P", f"MAN*CP*{attempt.tracking_number}"]
        body.append(f"HL*{hierarchy + 2}*{hierarchy + 1}*I")
        for item in package.contents:
            body += [f"LIN**SK*{item.stock_key.sku}", f"SN1**{item.quantity}*{UNIT}"]
        hierarchy += 2
    body.append(f"CTT*{hierarchy}")
    return _envelope(sender, receiver, control_number, "SH", "856", sent_at, body)
