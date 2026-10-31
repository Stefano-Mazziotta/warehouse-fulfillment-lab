from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Generic, TypeVar

from messaging.domain.inbound_message import InboundMessage

from .inbox_transaction import InboxTransaction

T = TypeVar("T", bound=InboxTransaction)


class IdempotentConsumer(Generic[T]):
    """Run the handler and remember the message in ONE transaction.

    Handler failure rolls back the inbox row, so the broker redelivery is processed
    again. Ordering is not assumed: handlers must tolerate any arrival order.
    """

    def __init__(
        self,
        transaction: Callable[[], AbstractContextManager[T]],
        consumer_name: str,
        handler: Callable[[T, InboundMessage], None],
    ) -> None:
        self._transaction = transaction
        self._consumer_name = consumer_name
        self._handler = handler

    def handle(self, message: InboundMessage) -> bool:
        with self._transaction() as transaction:
            if not transaction.record_inbox(self._consumer_name, message.message_id):
                return False
            self._handler(transaction, message)
            return True
