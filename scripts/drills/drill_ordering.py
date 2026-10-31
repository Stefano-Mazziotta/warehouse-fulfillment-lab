"""Drill 4: lifecycle events reach the read model in the wrong order."""
from demo_format import render_table
from demo_gateways import DynamoProjection
from drill_context import DrillContext
from drill_core import Check, Drill, DrillFailure, Explanation, Outcome
from drill_verdicts import never_regressed
from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.fulfillment_events import order_allocated, order_packed, order_shipped, picking_completed
from messaging.domain.inbound_message import InboundMessage
from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction
from orders.application.project_order_event import ProjectOrderEvent
from orders.application.projection_unavailable import ProjectionUnavailable
from orders.infrastructure.dynamodb_order_projection import DynamoDbOrderProjection


class RecordingProjection:
    """Delegates to the real DynamoDB projection and remembers whether each update advanced it."""

    def __init__(self, projection) -> None:
        self._projection = projection
        self.advanced: list[bool] = []

    def apply(self, change) -> bool:
        advanced = self._projection.apply(change)
        self.advanced.append(advanced)
        return advanced


def act(context: DrillContext) -> Outcome:
    ids, engine, say = context.ids, context.engine, context.say
    projection = DynamoDbOrderProjection(context.settings.dynamodb_url)
    try:
        projection.install()
    except ProjectionUnavailable as error:
        raise DrillFailure(f"DynamoDB Local is not usable: {error}") from error
    reader = DynamoProjection(context.settings.dynamodb_url)

    recording = RecordingProjection(projection)
    consumer = IdempotentConsumer(
        lambda: PostgresInboxTransaction(engine), ids.consumer_name, ProjectOrderEvent(recording))
    client, order = ids.client_id, ids.order_id
    # Business order: allocated(1) -> picked(2) -> packed(3) -> shipped(4). Arrival order: reversed.
    arrivals = [
        ("OrderShipped", order_shipped(client, order, "attempt-1", "FAKE-DRILL", ["box-1"])),
        ("OrderPacked", order_packed(client, order, ["box-1"])),
        ("PickingCompleted", picking_completed(client, order)),
        ("OrderAllocated", order_allocated(client, order, ids.warehouse_id, [(ids.line_id, ids.sku, 1)])),
        ("OrderShipped (again)", order_shipped(client, order, "attempt-1", "FAKE-DRILL", ["box-1"])),
    ]
    rows, stages, handled = [], [], []
    for number, (label, event) in enumerate(arrivals, 1):
        before = len(recording.advanced)
        applied = consumer.handle(InboundMessage(event.message_id, event.event_type, event.client_id, event.payload))
        item = reader.item(ids) or {}
        stages.append(int(item.get("stage", 0)))
        handled.append(applied)
        advanced = recording.advanced[before:] and recording.advanced[-1]
        rows.append([number, label, "yes" if applied else "no (inbox)", "yes" if advanced else "no",
                     item.get("stage", "-"), item.get("status", "-"), item.get("warehouse_id", "-"),
                     item.get("package_count", "-")])
    say(render_table(["#", "arrives", "inbox new?", "status advanced?", "stage", "status", "warehouse", "packages"], rows))

    final = reader.item(ids) or {}
    advanced = recording.advanced
    return Outcome((
        Check("the stage never went backwards across the five arrivals", never_regressed(stages)),
        Check("the final stage is the maximum stage seen (4, SHIPPED)", final.get("stage") == 4 and final.get("status") == "SHIPPED"),
        Check("only the first (highest) event advanced the status; the three late ones were stale",
              advanced == [True, False, False, False]),
        Check("a late event still contributed an immutable fact (the warehouse from OrderAllocated)",
              final.get("warehouse_id") == ids.warehouse_id),
        Check("the repeated OrderShipped was absorbed by the inbox before reaching the projection",
              handled[-1] is False and len(advanced) == 4),
    ))


DRILL = Drill(
    4, "out-of-order-events", "Events arrive out of order",
    "The read model (DynamoDB) is fed by lifecycle events. Because of a retry queue and parallel "
    "consumers, OrderShipped arrives first, then OrderPacked, PickingCompleted and finally OrderAllocated; "
    "OrderShipped is then redelivered once more.",
    "After each arrival, what stage and status does the projection show? Can an old event move the order "
    "back to ALLOCATED? Which late event still adds something, and what absorbs the final duplicate?",
    Explanation(
        invariant="an order's projected status never regresses: the final stage is the maximum event stage",
        mechanism="events carry no version, so the lifecycle stage (1-4) is the version; DynamoDB applies "
                  "status under the condition 'no stage yet OR stage < :new', so stale events fail the "
                  "condition and change nothing, while immutable facts (warehouse, package count) are set "
                  "unconditionally; exact redeliveries never get that far (inbox)",
        without="last-write-wins: the late OrderAllocated overwrites SHIPPED and the dashboard shows a "
                "shipped order as merely allocated until someone notices",
        trade_off="stage ordering assumes a fact happens once and the lifecycle only moves forward "
                  "(it would break for re-opened orders); an event type unknown to the stage table is "
                  "ignored; CREATED and PICKING emit no events, so they are invisible here"),
    act)
