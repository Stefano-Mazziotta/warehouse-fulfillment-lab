"""The reader is a teaching tool, not a validating X12 parser."""
import pytest

from integrations.edi.documents import read_order_request, read_ship_advice
from integrations.edi.x12 import EdiError, read_interchange

from edi_support import fixture


def test_envelope_exposes_partner_control_number_and_set():
    interchange = read_interchange(fixture("940_warehouse_shipping_order.edi"))

    assert interchange.sender_id == "ACMEBRANDS"
    assert interchange.receiver_id == "LABWMS"
    assert interchange.control_number == "000000202"
    assert interchange.transaction_set == "940"
    assert interchange.idempotency_key == "ACMEBRANDS:000000202"


def test_delimiters_come_from_the_isa_header_not_from_constants():
    text = fixture("940_warehouse_shipping_order.edi")
    # Same interchange, different declared delimiters: element "|" and terminator "!".
    custom = text.replace("*", "|").replace("~", "!")

    request = read_order_request(read_interchange(custom))

    assert request.order_number == "SO-1001"
    assert [(line.sku, line.quantity) for line in request.lines] == [
        ("SKU-MUG-RED", 2), ("SKU-TEE-L", 1)]


def test_reads_850_purchase_order_business_fields():
    request = read_order_request(read_interchange(fixture("850_purchase_order.edi")))

    assert request.transaction_set == "850"
    assert request.order_number == "PO-4500012345"
    assert request.ship_to == "Jane Example Store 12"
    assert request.warehouse_id is None
    assert [(line.line_id, line.sku, line.quantity) for line in request.lines] == [
        ("1", "SKU-MUG-RED", 2), ("2", "SKU-TEE-L", 1)]


def test_reads_940_warehouse_shipping_order_business_fields():
    request = read_order_request(read_interchange(fixture("940_warehouse_shipping_order.edi")))

    assert request.transaction_set == "940"
    assert request.order_number == "SO-1001"
    assert request.ship_to == "Jane Example Store 12"
    assert request.warehouse_id == "WH-EAST"
    assert [(line.line_id, line.sku, line.quantity) for line in request.lines] == [
        ("1", "SKU-MUG-RED", 2), ("2", "SKU-TEE-L", 1)]


def test_reads_945_shipping_advice_business_fields():
    advice = read_ship_advice(read_interchange(fixture("945_warehouse_shipping_advice.edi")))

    assert advice.transaction_set == "945"
    assert advice.order_number == "SO-1001"
    assert advice.shipment_id == "4d3e2336-7c55-5306-a2d6-3de5784db19f"
    assert advice.tracking_numbers == ("TRK-000123",)
    assert [(line.sku, line.quantity) for line in advice.lines] == [
        ("SKU-MUG-RED", 2), ("SKU-TEE-L", 1)]


def test_reads_856_advance_ship_notice_business_fields():
    advice = read_ship_advice(read_interchange(fixture("856_advance_ship_notice.edi")))

    assert advice.transaction_set == "856"
    assert advice.order_number == "PO-4500012345"
    assert advice.shipment_id == "4d3e2336-7c55-5306-a2d6-3de5784db19f"
    # Both packages carry the same order-level tracking number; it is reported once.
    assert advice.tracking_numbers == ("TRK-000123",)
    assert [(line.sku, line.quantity) for line in advice.lines] == [
        ("SKU-MUG-RED", 2), ("SKU-TEE-L", 1)]


def test_wrong_document_kind_is_refused_by_each_extractor():
    shipping_order = read_interchange(fixture("940_warehouse_shipping_order.edi"))
    advice = read_interchange(fixture("945_warehouse_shipping_advice.edi"))

    with pytest.raises(EdiError, match="945"):
        read_order_request(advice)
    with pytest.raises(EdiError, match="940"):
        read_ship_advice(shipping_order)


@pytest.mark.parametrize("cut", [60, 106, 250])
def test_truncated_file_fails_with_clear_error(cut):
    text = fixture("940_warehouse_shipping_order.edi")[:cut]

    with pytest.raises(EdiError):
        read_interchange(text)


def test_missing_trailer_names_the_truncation():
    text = fixture("940_warehouse_shipping_order.edi")
    without_iea = text[: text.index("IEA")]

    with pytest.raises(EdiError, match="IEA"):
        read_interchange(without_iea)


def test_trailer_control_number_must_match_header():
    text = fixture("940_warehouse_shipping_order.edi").replace("IEA*1*000000202", "IEA*1*000000999")

    with pytest.raises(EdiError, match="control number"):
        read_interchange(text)


def test_non_x12_text_is_refused():
    with pytest.raises(EdiError, match="ISA"):
        read_interchange("hello world")


def test_bad_quantity_is_an_error_not_a_zero():
    text = fixture("940_warehouse_shipping_order.edi").replace("W01*2*EA", "W01*two*EA")

    with pytest.raises(EdiError, match="quantity"):
        read_order_request(read_interchange(text))


def test_order_without_lines_is_refused():
    text = fixture("940_warehouse_shipping_order.edi")
    no_lines = "\n".join(row for row in text.splitlines() if not row.startswith("W01"))

    with pytest.raises(EdiError, match="line"):
        read_order_request(read_interchange(no_lines))
