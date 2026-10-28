"""Operate the order projection: `run` feeds it from RabbitMQ, `rebuild` replays the outbox.

    LAB_DATABASE_URL, LAB_DYNAMODB_URL (and LAB_AMQP_URL for `run`) must be set.
"""
import os
import signal
import sys
import threading
from collections.abc import Mapping, Sequence

from sqlalchemy import create_engine

from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction
from orders.application.rebuild_order_projection import RebuildOrderProjection

from .dynamodb_order_projection import DynamoDbOrderProjection
from .order_projection_worker import build_order_projection_runner
from .postgres_outbox_order_events import PostgresOutboxOrderEvents

USAGE = "usage: order_projection_cli (run | rebuild)"


def main(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    if len(argv) != 1 or argv[0] not in ("run", "rebuild"):
        print(USAGE, file=sys.stderr)
        return 2
    required = ["LAB_DATABASE_URL", "LAB_DYNAMODB_URL"] + (["LAB_AMQP_URL"] if argv[0] == "run" else [])
    missing = [name for name in required if not environ.get(name)]
    if missing:
        print(f"Set {', '.join(missing)}", file=sys.stderr)
        return 2

    engine = create_engine(environ["LAB_DATABASE_URL"])
    projection = DynamoDbOrderProjection(environ["LAB_DYNAMODB_URL"])
    projection.install()
    if argv[0] == "rebuild":
        replayed = RebuildOrderProjection(projection, PostgresOutboxOrderEvents(engine)).run()
        print(f"replayed {replayed} order events")
        return 0

    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    runner = build_order_projection_runner(
        lambda: PostgresInboxTransaction(engine), environ["LAB_AMQP_URL"], projection)
    runner.run(stop.is_set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], os.environ))
