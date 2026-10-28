from messaging.domain.inbound_message import InboundMessage

from orders.domain import OrderStatus

from .order_projection import OrderProjection, OrderProjectionUpdate

# The published events carry no version or sequence number, but a fulfillment fact happens at
# most once per order and the lifecycle only moves forward, so the position of an event in
# that lifecycle is its version. Cancellation is possible only before picking, so it is never
# racing the later stages; it ranks last because it is terminal. StartPicking and CreateOrder
# publish nothing, so PICKING and CREATED orders are invisible here: a known gap.
STAGES: dict[str, tuple[int, OrderStatus]] = {
    "OrderAllocated": (1, OrderStatus.ALLOCATED),
    "PickingCompleted": (2, OrderStatus.PICKED),
    "OrderPacked": (3, OrderStatus.PACKED),
    "OrderShipped": (4, OrderStatus.SHIPPED),
    "OrderCancelled": (5, OrderStatus.CANCELLED),
}


class ProjectOrderEvent:
    """Fold one fulfillment event into the read model.

    Used as the IdempotentConsumer handler (the inbox drops redeliveries) and by the rebuild,
    which has no inbox: duplicates and stale events are absorbed by the projection itself.
    """

    def __init__(self, projection: OrderProjection) -> None:
        self._projection = projection

    def __call__(self, transaction: object, message: InboundMessage) -> None:
        self.project(message)

    def project(self, message: InboundMessage) -> bool:
        change = self._translate(message)
        return change is not None and self._projection.apply(change)

    @staticmethod
    def _translate(message: InboundMessage) -> OrderProjectionUpdate | None:
        stage = STAGES.get(message.event_type)
        if stage is None:
            return None
        payload = message.payload
        # A missing key raises: a malformed event must reach the DLQ, not become a wrong row.
        facts: dict[str, object] = {}
        if message.event_type == "OrderAllocated":
            facts = {"warehouse_id": payload["warehouse_id"], "line_count": len(payload["lines"])}
        elif message.event_type == "OrderPacked":
            facts = {"package_count": len(payload["package_ids"])}
        elif message.event_type == "OrderShipped":
            facts = {"package_count": len(payload["package_ids"]),
                     "tracking_number": payload["tracking_number"]}
        return OrderProjectionUpdate(
            message.client_id, payload["order_id"], message.message_id, stage[1], stage[0], **facts)
