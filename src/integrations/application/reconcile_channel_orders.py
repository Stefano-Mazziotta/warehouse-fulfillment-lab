from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone

from integrations.domain.channel_event import ChannelEvent
from integrations.domain.reconciliation_report import ReconciliationReport

from .receive_channel_event import ReceiveChannelEvent
from .reconciliation_transaction import ReconciliationTransaction
from .sales_channel_port import SalesChannelPort


class ReconcileChannelOrders:
    """Poll the source of truth and feed what we missed through the normal ingest path.

    One page per checkpoint transaction: lock the checkpoint, read the page, ingest
    every order (each in its own commit), and only then advance the checkpoint. A
    crash anywhere before that re-reads the page, which is harmless because ingest
    is idempotent. A run starts `overlap` before the checkpoint to catch orders
    committed late or stamped by a skewed clock, then walks forward page by page with
    its own read cursor (which may sit below the checkpoint); the durable checkpoint
    itself only ever moves forward.
    """

    def __init__(
        self,
        channel: SalesChannelPort,
        receiver: ReceiveChannelEvent,
        checkpoints: Callable[[], AbstractContextManager[ReconciliationTransaction]],
        source: str,
        *,
        page_size: int = 50,
        overlap: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self._channel = channel
        self._receiver = receiver
        self._checkpoints = checkpoints
        self._source = source
        self._page_size = page_size
        self._overlap = overlap
        self._clock = clock

    def execute(self, client_id: str) -> ReconciliationReport:
        report = ReconciliationReport()
        position = None            # this run's read cursor; the checkpoint is separate
        first_page = True
        while True:
            with self._checkpoints() as checkpoint:
                saved = checkpoint.lock_cursor(self._source, client_id)
                start = (saved.minus(self._overlap) if saved else None) if first_page else position
                page = self._channel.list_orders_updated_since(client_id, start, self._page_size)
                page_durable = True
                for order in page.orders:
                    report.examined += 1
                    try:
                        report.record(self._receiver.execute(ChannelEvent.for_reconciliation(order)))
                    except Exception:
                        report.failed += 1
                        page_durable = False
                if not page_durable:
                    return report
                cursor = page.next_cursor
                if cursor is not None and (saved is None or cursor > saved):
                    checkpoint.advance(self._source, client_id, cursor, self._clock())
            first_page = False
            position = page.next_cursor
            if not page.has_more:
                return report
