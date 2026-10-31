from drill_edi import TEMPLATE, build_940
from integrations.edi.order_intake import to_order
from integrations.edi.documents import read_order_request
from integrations.edi.x12 import read_interchange

SENDER = "D1029101530ab12"


def build(**options):
    values = {"sender": SENDER, "order_number": "SO-77", "control_number": "010291015"} | options
    return build_940(TEMPLATE.read_text(), **values)


def test_the_re_addressed_940_keeps_the_fixed_width_isa_and_names_the_new_sender():
    interchange = read_interchange(build())

    assert interchange.sender_id == SENDER
    assert interchange.control_number == "010291015"
    assert interchange.idempotency_key == f"{SENDER}:010291015"


def test_the_control_number_changes_in_the_header_and_the_trailer_together():
    text = build(control_number="110291015")

    assert text.count("110291015") == 2 and "000000202" not in text


def test_the_order_number_and_quantity_reach_the_mapped_order():
    interchange = read_interchange(build(quantity=5))
    order = to_order(interchange, read_order_request(interchange), None)

    assert order.key.client_id == SENDER and order.key.order_id == "SO-77"
    assert order.lines[0].quantity == 5
