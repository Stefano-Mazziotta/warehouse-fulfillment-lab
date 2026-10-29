"""Child processes that die on purpose, so the parent can watch what survives.

    drill_child.py consume-then-crash CLIENT QUEUE EVENT_TYPE CONSUMER
    drill_child.py relay-then-crash CLIENT PUBLISHES_BEFORE_CRASH

Run with LAB_DATABASE_URL and LAB_AMQP_URL set. Both modes end with SIGKILL, never a clean exit.
"""
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine

from drill_effects import runner_for, stock_receipt_consumer
from messaging.application.outbox_relay import OutboxRelay
from messaging.infrastructure.rabbitmq_publisher import RabbitMqPublisher

# The demo's client-scoped outbox keeps the relay from touching anyone else's pending rows.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
from outbox_relay_worker import ClientScopedOutbox  # noqa: E402


def die() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


class CrashAfterCommit:
    """The real consumer handles (and COMMITS) the message, then the process dies before the ack."""

    def __init__(self, real) -> None:
        self._real = real

    def handle(self, message) -> bool:
        self._real.handle(message)
        die()
        return True


class CrashAfterPublishing:
    """Publishes through the real publisher (confirmed by the broker), then dies after `limit` messages."""

    def __init__(self, real, limit: int) -> None:
        self._real, self._limit, self._count = real, limit, 0

    def publish(self, message) -> None:
        self._real.publish(message)
        self._count += 1
        if self._count >= self._limit:
            die()


def main(argv: list[str]) -> int:
    engine = create_engine(os.environ["LAB_DATABASE_URL"])
    amqp_url = os.environ["LAB_AMQP_URL"]
    mode = argv[0]
    if mode == "consume-then-crash":
        _, client, queue, event_type, consumer_name = argv
        runner = runner_for(amqp_url, queue, event_type, CrashAfterCommit(stock_receipt_consumer(engine, consumer_name)))
        runner.run(lambda: False)
    elif mode == "relay-then-crash":
        _, client, limit = argv
        OutboxRelay(
            lambda: ClientScopedOutbox(engine, client), CrashAfterPublishing(RabbitMqPublisher(amqp_url), int(limit)),
            lambda: datetime.now(timezone.utc)).run_once()
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 1  # reaching here means the crash did not happen


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
