"""Pull only the business fields the lab acts on out of an 850/940/945/856.

Pricing, dates, addresses beyond the ship-to name, packaging hierarchy and every other
segment are ignored on purpose. Real partners each have their own implementation guide.
"""
from dataclasses import dataclass

from .x12 import EdiError, Interchange, Segment

SKU_QUALIFIER = "SK"


@dataclass(frozen=True)
class EdiOrderLine:
    line_id: str
    sku: str
    quantity: int


@dataclass(frozen=True)
class OrderRequest:
    """An 850 or 940: somebody asks for goods to be shipped."""

    transaction_set: str
    order_number: str
    ship_to: str
    warehouse_id: str | None
    lines: tuple[EdiOrderLine, ...]


@dataclass(frozen=True)
class AdviceLine:
    sku: str
    quantity: int


@dataclass(frozen=True)
class ShipAdvice:
    """A 945 or 856: the warehouse says what physically left the building."""

    transaction_set: str
    order_number: str
    shipment_id: str
    tracking_numbers: tuple[str, ...]
    lines: tuple[AdviceLine, ...]


def _require(interchange: Interchange, *accepted: str) -> None:
    if interchange.transaction_set not in accepted:
        raise EdiError(
            f"Expected transaction set {' or '.join(accepted)}, got {interchange.transaction_set}"
        )


def _quantity(raw: str) -> int:
    try:
        quantity = int(raw)
    except ValueError:
        raise EdiError(f"Invalid quantity {raw!r}") from None
    if quantity <= 0:
        raise EdiError(f"Invalid quantity {raw!r}")
    return quantity


def _required(segment: Segment | None, tag: str) -> Segment:
    if segment is None:
        raise EdiError(f"Required segment {tag} is missing")
    return segment


def _name_for(interchange: Interchange, entity_code: str) -> Segment | None:
    return next((s for s in interchange.find("N1") if s.element(1) == entity_code), None)


def _tracking_numbers(interchange: Interchange) -> tuple[str, ...]:
    # MAN01 "CP" is the carrier-assigned package identifier. Order-level tracking repeats
    # on every package, so duplicates are collapsed.
    return tuple(dict.fromkeys(
        s.element(2) for s in interchange.find("MAN") if s.element(1) == "CP" and s.element(2)
    ))


def read_order_request(interchange: Interchange) -> OrderRequest:
    _require(interchange, "850", "940")
    ship_to = _name_for(interchange, "ST")
    if interchange.transaction_set == "850":
        order_number = _required(interchange.first("BEG"), "BEG").element(3)
        lines = tuple(
            EdiOrderLine(s.element(1), s.element(7), _quantity(s.element(2)))
            for s in interchange.find("PO1") if s.element(6) == SKU_QUALIFIER
        )
        warehouse_id = None
    else:
        order_number = _required(interchange.first("W05"), "W05").element(2)
        lines = tuple(
            # The 940 has no line number here, so the position becomes the line ID.
            EdiOrderLine(str(position), s.element(5), _quantity(s.element(1)))
            for position, s in enumerate(
                (s for s in interchange.find("W01") if s.element(4) == SKU_QUALIFIER), start=1
            )
        )
        warehouse = _name_for(interchange, "WH")
        warehouse_id = warehouse.element(4) if warehouse else None
    if not order_number:
        raise EdiError("Order number is missing")
    if not lines:
        raise EdiError("Order carries no SKU lines")
    return OrderRequest(
        interchange.transaction_set, order_number,
        ship_to.element(2) if ship_to else "", warehouse_id, lines,
    )


def read_ship_advice(interchange: Interchange) -> ShipAdvice:
    _require(interchange, "945", "856")
    if interchange.transaction_set == "945":
        header = _required(interchange.first("W06"), "W06")
        order_number, shipment_id = header.element(2), header.element(4)
        lines = tuple(
            AdviceLine(s.element(8), _quantity(s.element(3)))
            for s in interchange.find("W12") if s.element(7) == SKU_QUALIFIER
        )
    else:
        shipment_id = _required(interchange.first("BSN"), "BSN").element(2)
        order_number = _required(interchange.first("PRF"), "PRF").element(1)
        lines = _notice_lines(interchange)
    if not order_number or not shipment_id:
        raise EdiError("Order or shipment identifier is missing")
    if not lines:
        raise EdiError("Advice carries no SKU lines")
    return ShipAdvice(
        interchange.transaction_set, order_number, shipment_id,
        _tracking_numbers(interchange), lines,
    )


def _notice_lines(interchange: Interchange) -> tuple[AdviceLine, ...]:
    # In an 856 the SKU (LIN) and its shipped quantity (SN1) are separate segments.
    lines: list[AdviceLine] = []
    sku = None
    for segment in interchange.segments:
        if segment.tag == "LIN":
            sku = segment.element(3) if segment.element(2) == SKU_QUALIFIER else None
        elif segment.tag == "SN1" and sku:
            lines.append(AdviceLine(sku, _quantity(segment.element(2))))
            sku = None
    return tuple(lines)
