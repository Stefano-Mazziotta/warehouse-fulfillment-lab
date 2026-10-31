from collections.abc import Callable

from messaging.application.publish_failed import PublishFailed
from messaging.domain.outbox_message import OutboxMessage


class InMemoryPublisher:
    """Records deliveries and fails on demand, to rehearse a broker outage."""

    def __init__(self) -> None:
        self.published: list[OutboxMessage] = []
        self.attempts = 0
        self._failures_left = 0
        self._failure_text = ""
        self._fail_when: Callable[[OutboxMessage], bool] | None = None

    def fail_next(self, count: int, error: str = "broker unavailable") -> None:
        self._failures_left, self._failure_text = count, error

    def fail_when(self, predicate: Callable[[OutboxMessage], bool]) -> None:
        self._fail_when = predicate

    def publish(self, message: OutboxMessage) -> None:
        self.attempts += 1
        if self._failures_left > 0:
            self._failures_left -= 1
            raise PublishFailed(self._failure_text)
        if self._fail_when is not None and self._fail_when(message):
            raise PublishFailed("rejected by predicate")
        self.published.append(message)
