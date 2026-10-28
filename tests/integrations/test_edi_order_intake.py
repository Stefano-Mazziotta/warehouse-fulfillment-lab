import pytest

from integrations.edi.order_intake import EdiOrderIntake
from integrations.edi.x12 import EdiError
from orders.domain import OrderError, OrderKey, OrderLine

from channel_support import InMemoryIngestStore
from edi_support import fixture

KEY = OrderKey("ACMEBRANDS", "SO-1001")


def intake(store=None, **options):
    store = store or InMemoryIngestStore()
    return store, EdiOrderIntake(store.transaction, **options)


def test_940_becomes_an_order_through_the_existing_create_use_case():
    store, edi = intake()

    assert edi.receive(fixture("940_warehouse_shipping_order.edi")) is True

    order = store.orders[KEY]
    assert order.warehouse_id == "WH-EAST"
    assert order.lines == (OrderLine("1", "SKU-MUG-RED", 2), OrderLine("2", "SKU-TEE-L", 1))


def test_850_maps_the_same_way_once_a_warehouse_is_chosen_at_the_edge():
    store, edi = intake(default_warehouse_id="WH-EAST")

    edi.receive(fixture("850_purchase_order.edi"))

    assert store.orders[OrderKey("RETAILCO", "PO-4500012345")].warehouse_id == "WH-EAST"


def test_850_without_any_warehouse_is_refused_and_creates_nothing():
    store, edi = intake()

    with pytest.raises(EdiError, match="warehouse"):
        edi.receive(fixture("850_purchase_order.edi"))

    assert store.orders == {} and store.inbox == set()


def test_duplicate_interchange_is_detected_and_creates_no_second_order():
    store, edi = intake()
    text = fixture("940_warehouse_shipping_order.edi")

    assert edi.receive(text) is True
    # CreateOrder is idempotent anyway, so prove the inbox short-circuits before it:
    # a duplicate that reached the use case would hit this injected failure.
    store.fail_on = "SO-1001"
    assert edi.receive(text) is False

    assert list(store.orders) == [KEY]
    assert store.inbox == {("edi-order-intake", "ACMEBRANDS:000000202")}


def test_resend_under_a_new_control_number_is_absorbed_by_idempotent_create():
    store, edi = intake()
    text = fixture("940_warehouse_shipping_order.edi")
    resent = text.replace("000000202", "000000203")

    edi.receive(text)
    assert edi.receive(resent) is True

    assert list(store.orders) == [KEY]


def test_same_order_with_different_content_is_not_silently_overwritten():
    store, edi = intake()
    text = fixture("940_warehouse_shipping_order.edi")
    amended = text.replace("W01*2*EA", "W01*5*EA").replace("000000202", "000000203")

    edi.receive(text)
    with pytest.raises(OrderError):
        edi.receive(amended)

    assert store.orders[KEY].lines[0].quantity == 2
    # The failed attempt rolled back its inbox row, so a corrected resend is not blocked.
    assert ("edi-order-intake", "ACMEBRANDS:000000203") not in store.inbox


@pytest.mark.parametrize("cut", [150, 380])
def test_truncated_file_fails_clearly_and_creates_nothing(cut):
    store, edi = intake()

    with pytest.raises(EdiError):
        edi.receive(fixture("940_warehouse_shipping_order.edi")[:cut])

    assert store.orders == {} and store.inbox == set()


def test_wrong_document_for_this_intake_creates_nothing():
    store, edi = intake()

    with pytest.raises(EdiError, match="945"):
        edi.receive(fixture("945_warehouse_shipping_advice.edi"))

    assert store.orders == {} and store.inbox == set()
