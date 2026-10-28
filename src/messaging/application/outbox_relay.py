from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime

from messaging.domain.outbox_status import OutboxStatus
from messaging.domain.retry_policy import RetryPolicy

from .message_publisher import MessagePublisher
from .outbox_transaction import OutboxTransaction
from .publish_failed import PublishFailed


@dataclass(frozen=True)
class RelayResult:
    published: int = 0
    retried: int = 0
    dead: int = 0


class OutboxRelay:
    """Deliver at least once: publish, then mark; a crash in between means redelivery.

    The claim lock is held while publishing, so concurrent relays take disjoint
    batches. A slow broker therefore holds row locks; keep batches small and the
    publisher's timeout short.
    """

    def __init__(
        self,
        transaction: Callable[[], AbstractContextManager[OutboxTransaction]],
        publisher: MessagePublisher,
        clock: Callable[[], datetime],
        policy: RetryPolicy = RetryPolicy(),
        batch_size: int = 50,
    ) -> None:
        self._transaction = transaction
        self._publisher = publisher
        self._clock = clock
        self._policy = policy
        self._batch_size = batch_size

    def run_once(self) -> RelayResult:
        published = retried = dead = 0
        with self._transaction() as transaction:
            for message in transaction.claim_due(self._clock(), self._batch_size):
                try:
                    self._publisher.publish(message)
                except PublishFailed as error:
                    failed = message.failed(str(error), self._clock(), self._policy)
                    transaction.save(failed)
                    if failed.status == OutboxStatus.DEAD:
                        dead += 1
                    else:
                        retried += 1
                else:
                    transaction.save(message.published())
                    published += 1
        return RelayResult(published, retried, dead)
