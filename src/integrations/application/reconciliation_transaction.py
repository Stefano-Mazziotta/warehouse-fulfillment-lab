from datetime import datetime
from typing import Protocol

from integrations.domain.channel_cursor import ChannelCursor


class ReconciliationTransaction(Protocol):

    def lock_cursor(self, source: str, client_id: str) -> ChannelCursor | None:
        """Read the checkpoint and hold it, so one reconciler per owner works at a time."""

    def advance(
        self, source: str, client_id: str, cursor: ChannelCursor, at: datetime
    ) -> None: ...
