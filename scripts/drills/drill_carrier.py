"""Drill 2: the carrier creates the shipment, the response is lost."""
from demo_format import render_table
from drill_context import DrillContext
from drill_core import Check, Drill, Explanation, Outcome
from drill_fulfillment import pack_order, transaction_factory
from shipping.application.ship_order import ShipOrder
from shipping.domain.shipment_status import ShipmentStatus
from shipping.infrastructure.postgres_fake_carrier import PostgresFakeCarrier

QUANTITY = 3


def act(context: DrillContext) -> Outcome:
    ids, engine, say, truth = context.ids, context.engine, context.say, context.truth
    truth.seed_stock(ids, QUANTITY)
    key = pack_order(context, ids.order_id, QUANTITY)

    def state() -> dict:
        stock = truth.rows("SELECT on_hand, allocated, picked FROM inventory_balances WHERE client_id = :c", c=ids.client_id)[0]
        return {
            "order": truth.scalar("SELECT status FROM orders WHERE client_id = :c AND order_id = :o", c=ids.client_id, o=ids.order_id),
            "attempt": truth.scalar("SELECT status FROM shipping_attempts WHERE client_id = :c", c=ids.client_id),
            "carrier_shipments": truth.scalar("SELECT count(*) FROM fake_carrier_shipments WHERE client_id = :c", c=ids.client_id),
            "shipped_events": truth.scalar(
                "SELECT count(*) FROM outbox_messages WHERE client_id = :c AND event_type = 'OrderShipped'", c=ids.client_id),
            **stock,
        }

    show = lambda label, row: say(f"{label}\n" + render_table(list(row), [list(row.values())]))  # noqa: E731
    show("packed and ready to ship:", {"order": "PACKED", "on_hand": QUANTITY, "allocated": QUANTITY, "picked": QUANTITY})

    carrier = PostgresFakeCarrier(engine)
    carrier.lose_next_create_response = True
    say("shipOrder #1: the carrier commits the shipment, then the response is lost (timeout)")
    first = ShipOrder(transaction_factory(engine), carrier).execute(key)
    after_loss = state()
    show(f"after the lost response (create calls: {carrier.create_calls}):", after_loss)

    # A new adapter instance models a restarted worker: nothing in memory remembers the first call.
    restarted = PostgresFakeCarrier(engine)
    say("shipOrder #2 (retry, fresh process): look the shipment up by the attempt id first")
    second = ShipOrder(transaction_factory(engine), restarted).execute(key)
    after_retry = state()
    show(f"after the retry (create calls: {restarted.create_calls}):", after_retry)

    return Outcome((
        Check("the lost response left the attempt UNKNOWN, not failed and not retried blindly",
              first.status == ShipmentStatus.UNKNOWN and after_loss["attempt"] == "UNKNOWN"),
        Check("the carrier had really created the shipment while the order was still PACKED with stock untouched",
              after_loss["carrier_shipments"] == 1 and after_loss["order"] == "PACKED"
              and (after_loss["on_hand"], after_loss["allocated"]) == (QUANTITY, QUANTITY)),
        Check("the retry found the shipment by lookup and made no create call", restarted.create_calls == 0),
        Check("same attempt id, now SHIPPED with a tracking number",
              second.attempt_id == first.attempt_id and second.status == ShipmentStatus.SHIPPED
              and bool(second.tracking_number)),
        Check("one carrier shipment, stock decremented exactly once (on_hand 3 -> 0), one OrderShipped event",
              after_retry["carrier_shipments"] == 1 and (after_retry["on_hand"], after_retry["allocated"], after_retry["picked"]) == (0, 0, 0)
              and after_retry["shipped_events"] == 1 and after_retry["order"] == "SHIPPED"),
    ))


DRILL = Drill(
    2, "carrier-timeout", "The carrier times out after creating the shipment",
    "An order is packed and shipOrder calls the carrier. The carrier creates the shipment and "
    "commits it, but the response never reaches us: we only see a timeout.",
    "What state should the order, the shipping attempt and the stock be in right after the timeout? "
    "When the worker retries, does it create a second shipment? How many times is stock decremented?",
    Explanation(
        invariant="one order, one shipment, one stock decrement, whatever the network did",
        mechanism="the attempt row (with a deterministic id) is committed before the carrier call and no "
                  "WMS transaction spans the call; a timeout leaves it UNKNOWN; every retry asks the "
                  "carrier by attempt id first and only creates when the answer is an authoritative 'not found'",
        without="a naive retry creates a second label and a second parcel; or failing the order loses a "
                "shipment that physically exists and double-counts stock when someone retries manually",
        trade_off="needs a carrier that supports idempotent create or lookup by our id (the fake does; real "
                  "carriers vary); the order stays PACKED/UNKNOWN until reconciled, so something must retry"),
    act)
