"""A deliberately tiny X12 envelope reader.

This is NOT a validating parser. It does not check segment counts (SE01, GE01, IEA01),
qualifiers, code lists, element lengths or the functional group. It checks only what
teaches the integration lessons: the file is complete (ISA ... IEA) and the control
number is a usable idempotency handle.
It reads exactly one transaction (ST ... SE) per interchange; batches are refused, not split.
"""
from dataclasses import dataclass

# ISA is the one fixed-width segment, and it declares the delimiters used by the rest.
ISA_LENGTH = 106
ELEMENT_SEPARATOR_AT = 3
TERMINATOR_AT = 105


class EdiError(ValueError):
    """The file cannot be trusted; nothing from it may be applied."""


@dataclass(frozen=True)
class Segment:
    tag: str
    elements: tuple[str, ...]

    def element(self, position: int) -> str:
        # X12 element numbers are 1-based and trailing/empty elements are optional.
        return self.elements[position - 1] if position <= len(self.elements) else ""


@dataclass(frozen=True)
class Interchange:
    sender_id: str
    receiver_id: str
    control_number: str
    transaction_set: str
    segments: tuple[Segment, ...]

    @property
    def idempotency_key(self) -> str:
        # The control number is only unique per sender, so the partner is part of the key.
        # A partner that resets its counter would collide; that is a known EDI hazard.
        return f"{self.sender_id}:{self.control_number}"

    def find(self, tag: str) -> tuple[Segment, ...]:
        return tuple(segment for segment in self.segments if segment.tag == tag)

    def first(self, tag: str) -> Segment | None:
        found = self.find(tag)
        return found[0] if found else None


def read_interchange(text: str) -> Interchange:
    text = text.lstrip()
    if not text.startswith("ISA") or len(text) < ISA_LENGTH:
        raise EdiError("Not an X12 interchange: a complete ISA header is required")
    element_separator = text[ELEMENT_SEPARATOR_AT]
    terminator = text[TERMINATOR_AT]
    # Newlines between segments are cosmetic; the declared terminator is what counts.
    segments = tuple(
        Segment(parts[0], tuple(parts[1:]))
        for raw in text.split(terminator)
        if (parts := raw.strip().split(element_separator)) and parts[0]
    )
    isa, trailer = segments[0], segments[-1]
    if trailer.tag != "IEA":
        raise EdiError("Interchange is truncated: IEA trailer missing")
    if trailer.element(2) != isa.element(13):
        raise EdiError("IEA control number does not match the ISA header")
    starts = [s for s in segments if s.tag == "ST"]
    if not starts:
        raise EdiError("Interchange carries no transaction set (ST)")
    if len(starts) > 1:
        raise EdiError("Interchange carries more than one transaction set; this reader takes one transaction per interchange")
    transaction = starts[0]
    ends = [s for s in segments if s.tag == "SE"]
    if len(ends) != 1 or segments.index(ends[0]) < segments.index(transaction):
        raise EdiError("Transaction set is not closed by exactly one SE after its ST")
    if ends[0].element(2) != transaction.element(2):
        raise EdiError("SE control number does not match the ST header")
    return Interchange(
        sender_id=isa.element(6).strip(),
        receiver_id=isa.element(8).strip(),
        control_number=isa.element(13),
        transaction_set=transaction.element(1),
        segments=segments,
    )
