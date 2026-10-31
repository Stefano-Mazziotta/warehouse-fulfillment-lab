import strawberry
from strawberry import Info

from shipping.application.attempt_summary import AttemptSummary
from shipping.domain.shipping_attempt import ShippingAttempt

from ..graphql_context import GraphQLContext
from .shipment_attempt_type import ShipmentAttemptType
from .shipment_payload import ShipmentPayload


def _payload(attempt: ShippingAttempt) -> ShipmentPayload:
    summary = AttemptSummary(
        attempt.order_key.order_id, attempt.attempt_id, attempt.status,
        attempt.tracking_number, tuple(sorted(attempt.package_ids)))
    return ShipmentPayload(shipment=ShipmentAttemptType.from_summary(summary))


@strawberry.type
class ShippingMutation:

    @strawberry.mutation(description=(
        "Commits one shipping attempt, then asks the carrier. Idempotent: an uncertain carrier "
        "answer leaves status UNKNOWN and never creates a second shipment."))
    def ship_order(self, info: Info[GraphQLContext, None], order_id: str) -> ShipmentPayload:
        context = info.context
        return _payload(context.services.ship_order.execute(context.order_key(order_id)))

    @strawberry.mutation(description=(
        "Settles an open attempt by asking the carrier first. Idempotent."))
    def reconcile_shipment(self, info: Info[GraphQLContext, None], order_id: str) -> ShipmentPayload:
        context = info.context
        return _payload(context.services.reconcile_shipment.execute(context.order_key(order_id)))
