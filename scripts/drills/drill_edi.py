"""Drill 8: the same EDI document arrives twice, then again under a new control number."""
from pathlib import Path

from demo_format import render_table
from drill_context import DrillContext, ROOT_DIR
from drill_core import Check, Drill, Explanation, Outcome
from integrations.edi.order_intake import EdiOrderIntake
from integrations.edi.x12 import read_interchange
from integrations.infrastructure.postgres_ingest_transaction import PostgresIngestTransaction
from orders.domain import OrderError

TEMPLATE = ROOT_DIR / "fixtures" / "edi" / "940_warehouse_shipping_order.edi"


def build_940(template: str, *, sender: str, order_number: str, control_number: str, quantity: int = 2) -> str:
    """The sample 940 re-addressed from one sender, with its own order number and control number.

    ISA is fixed width, so ISA06 keeps its 15 characters; the control number appears in ISA13 and IEA02.
    """
    text = template.replace("ACMEBRANDS     ", sender.ljust(15)).replace("ACMEBRANDS", sender)
    return (text.replace("000000202", control_number)
            .replace("SO-1001", order_number)
            .replace("W01*2*EA", f"W01*{quantity}*EA"))


def act(context: DrillContext) -> Outcome:
    ids, engine, say, truth = context.ids, context.engine, context.say, context.truth
    sender, order_number = ids.client_id, f"SO-{ids.run_id}"
    digits = ids.run_id[:8]
    template = TEMPLATE.read_text()
    intake = EdiOrderIntake(lambda: PostgresIngestTransaction(engine))
    document = lambda control, quantity=2: build_940(  # noqa: E731
        template, sender=sender, order_number=order_number, control_number=control, quantity=quantity)

    def state() -> dict:
        return {
            "orders": truth.scalar("SELECT count(*) FROM orders WHERE client_id = :c", c=ids.client_id),
            "line qty": truth.scalar("SELECT quantity FROM order_lines WHERE client_id = :c AND line_id = '1'", c=ids.client_id),
            "inbox rows": truth.scalar(
                "SELECT count(*) FROM inbox_messages WHERE consumer_name = 'edi-order-intake' AND message_id LIKE :p",
                p=f"{ids.client_id}:%"),
        }

    steps = [
        ("1. first 940", "0" + digits, 2),
        ("2. exact resend (same ISA13)", "0" + digits, 2),
        ("3. resend, new ISA13, same payload", "1" + digits, 2),
        ("4. new ISA13, quantity 2 -> 5", "2" + digits, 5),
    ]
    rows, results = [], []
    for label, control, quantity in steps:
        text = document(control, quantity)
        key = read_interchange(text).idempotency_key
        try:
            result = "applied" if intake.receive(text) else "duplicate (inbox)"
        except OrderError as error:
            result = "REFUSED: " + str(error)
        results.append(result)
        now = state()
        rows.append([label, key, result, now["orders"], now["line qty"], now["inbox rows"]])
    say(render_table(["step", "idempotency key", "result", "orders", "line qty", "inbox rows"], rows))
    final = state()
    return Outcome((
        Check("the first document created the order", results[0] == "applied"),
        Check("the exact resend (same sender and ISA13) was detected as a duplicate; still one order, one inbox row",
              results[1] == "duplicate (inbox)" and rows[1][3:] == [1, 2, 1]),
        Check("the resend under a new control number passed the inbox but CreateOrder absorbed it: still one order, unchanged",
              results[2] == "applied" and rows[2][3:] == [1, 2, 2]),
        Check("the same order with a different payload was refused as a conflict and nothing was overwritten",
              results[3].startswith("REFUSED") and rows[3][3:] == [1, 2, 2]),
        Check("final state: one order of 2 units and two inbox rows (the refused document left none)",
              final == {"orders": 1, "line qty": 2, "inbox rows": 2}),
    ))


DRILL = Drill(
    8, "duplicate-edi", "An EDI document arrives twice",
    "A partner sends a 940 (warehouse shipping order). The VAN delivers the identical file twice. "
    "Later the partner resends it under a NEW interchange control number, and finally sends the same "
    "order number with a quantity changed from 2 to 5.",
    "For each of the four documents: is it applied, treated as a duplicate, or refused? How many orders "
    "and inbox rows exist after each? What is the idempotency key, and why is the sender part of it?",
    Explanation(
        invariant="one partner order number, one order: duplicates never multiply and a changed payload "
                  "never silently overwrites",
        mechanism="two layers: the inbox key (sender + ISA13 control number) drops an exact redelivery "
                  "before any business code runs; a resend under a new control number reaches CreateOrder, "
                  "which is idempotent for an identical payload and rejects a different one (its inbox "
                  "row rolls back, so a corrected resend is not blocked)",
        without="no inbox: every redelivery re-runs the use case (harmless for CreateOrder, harmful for "
                "anything with side effects); no payload comparison: an amended order silently rewrites "
                "an order the warehouse may already be picking",
        trade_off="control numbers are unique only per sender and a partner that resets its counter "
                  "collides with old keys; a rejected amendment needs a human or a defined amendment flow "
                  "(real EDI would send a 860/change order); the sender id comes from the unauthenticated ISA06"),
    act)
