"""Edge adapter: an 850/940 interchange becomes the lab's existing CreateOrder call.

Domain and application code know nothing about X12. Everything EDI-specific (partner
IDs, document layout, the interchange control number) stays on this side of the port.
"""
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.application.inbox_transaction import InboxTransaction
from messaging.domain.inbound_message import InboundMessage
from orders.application.create_order import CreateOrder
from orders.application.order_transaction import OrderTransaction
from orders.domain import Order, OrderKey, OrderLine

from .documents import OrderRequest, read_order_request
from .x12 import EdiError, Interchange, read_interchange

CONSUMER_NAME = "edi-order-intake"


class IntakeTransaction(OrderTransaction, InboxTransaction):
    """The inbox row and the order are written in one commit, like any other consumer."""


def to_order(interchange: Interchange, request: OrderRequest, default_warehouse_id: str | None) -> Order:
    warehouse_id = request.warehouse_id or default_warehouse_id
    if warehouse_id is None:
        raise EdiError("No warehouse: the document names none and no default is configured")
    return Order(
        # The sending partner owns the inventory and the order, as in a 3PL.
        OrderKey(interchange.sender_id, request.order_number),
        warehouse_id,
        tuple(OrderLine(line.line_id, line.sku, line.quantity) for line in request.lines),
    )


class EdiOrderIntake:

    def __init__(
        self,
        transaction: Callable[[], AbstractContextManager[IntakeTransaction]],
        default_warehouse_id: str | None = None,
    ) -> None:
        self._transaction = transaction
        self._default_warehouse_id = default_warehouse_id

    def receive(self, text: str) -> bool:
        """True when the interchange was applied, False when it was a duplicate."""
        # Parse and map before opening a transaction: a bad file touches nothing.
        interchange = read_interchange(text)
        order = to_order(interchange, read_order_request(interchange), self._default_warehouse_id)

        def create(transaction: IntakeTransaction, _message: InboundMessage) -> None:
            CreateOrder(lambda: nullcontext(transaction)).execute(order)

        message = InboundMessage(
            interchange.idempotency_key,
            f"edi.{interchange.transaction_set}",
            interchange.sender_id,
            {},
        )
        return IdempotentConsumer(self._transaction, CONSUMER_NAME, create).handle(message)
