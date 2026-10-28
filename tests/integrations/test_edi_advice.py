from datetime import datetime, timezone

import pytest

from integrations.edi.advice_check import MismatchCode, reconcile_advice
from integrations.edi.advice_writer import write_856, write_945
from integrations.edi.documents import read_ship_advice
from integrations.edi.x12 import EdiError, read_interchange
from inventory.domain import InventoryKey
from orders.domain import Order, OrderKey, OrderLine, OrderStatus
from packing.domain.package import Package
from packing.domain.package_item import PackageItem
from shipping.domain.carrier_receipt import CarrierReceipt
from shipping.domain.shipping_attempt import ShippingAttempt

from edi_support import fixture

KEY = OrderKey("ACMEBRANDS", "SO-1001")
SENT_AT = datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc)


def box(package_id, line_id, sku, quantity):
    stock = InventoryKey("ACMEBRANDS", sku, "WH-EAST", "A1")
    return Package(KEY, package_id, 100, 200, 150, 100, (PackageItem(KEY, line_id, stock, quantity),))


def order(status=OrderStatus.SHIPPED):
    return Order(KEY, "WH-EAST", (OrderLine("1", "SKU-MUG-RED", 2), OrderLine("2", "SKU-TEE-L", 1)), status)


def opened():
    return ShippingAttempt.open(KEY, (box("box-1", "1", "SKU-MUG-RED", 2), box("box-2", "2", "SKU-TEE-L", 1)))


def shipped(tracking="TRK-000123"):
    attempt = opened()
    return attempt.confirm(CarrierReceipt(KEY, attempt.attempt_id, attempt.package_ids, tracking))


def test_945_derived_from_shipped_order_matches_the_sample_file():
    text = write_945(order(), shipped(), sender="LABWMS", receiver="ACMEBRANDS",
                     control_number=303, sent_at=SENT_AT)

    assert text == fixture("945_warehouse_shipping_advice.edi")


def test_856_derived_from_shipped_order_matches_the_sample_file():
    text = write_856(order(), shipped(), ship_to="Jane Example Store 12", customer_po="PO-4500012345",
                     sender="ACMEBRANDS", receiver="RETAILCO", control_number=404, sent_at=SENT_AT)

    assert text == fixture("856_advance_ship_notice.edi")


def test_derived_documents_survive_the_reader_round_trip():
    attempt = shipped()
    text = write_945(order(), attempt, sender="LABWMS", receiver="ACMEBRANDS",
                     control_number=7, sent_at=SENT_AT)

    advice = read_ship_advice(read_interchange(text))

    assert (advice.order_number, advice.shipment_id) == ("SO-1001", attempt.attempt_id)
    assert reconcile_advice(advice, attempt) == ()


@pytest.mark.parametrize("attempt", [opened(), opened().mark_unknown()])
def test_no_advice_is_written_for_a_shipment_that_has_not_happened(attempt):
    with pytest.raises(EdiError, match="SHIPPED"):
        write_945(order(OrderStatus.PACKED), attempt, sender="LABWMS", receiver="ACMEBRANDS",
                  control_number=1, sent_at=SENT_AT)


def inbound_945():
    return read_ship_advice(read_interchange(fixture("945_warehouse_shipping_advice.edi")))


def test_945_for_an_order_we_never_shipped_is_a_mismatch_not_an_acceptance():
    mismatches = reconcile_advice(inbound_945(), None)

    assert [m.code for m in mismatches] == [MismatchCode.NOT_SHIPPED]


def test_945_for_an_attempt_still_unknown_is_a_mismatch():
    mismatches = reconcile_advice(inbound_945(), opened().mark_unknown())

    assert [m.code for m in mismatches] == [MismatchCode.NOT_SHIPPED]


def test_matching_advice_reconciles_cleanly():
    assert reconcile_advice(inbound_945(), shipped()) == ()


def test_each_disagreement_is_reported_separately():
    other_tracking = reconcile_advice(inbound_945(), shipped("TRK-999999"))
    assert [m.code for m in other_tracking] == [MismatchCode.TRACKING_DIFFERS]

    short = inbound_945().__class__(
        "945", "SO-1001", "other-shipment", ("TRK-000123",), inbound_945().lines[:1])
    codes = {m.code for m in reconcile_advice(short, shipped())}
    assert codes == {MismatchCode.SHIPMENT_ID_DIFFERS, MismatchCode.QUANTITY_DIFFERS}
