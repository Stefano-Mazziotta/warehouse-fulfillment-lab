"""Database-free outbox and inbox transactions with real rollback semantics."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from messaging.domain.integration_event import IntegrationEvent
from messaging.domain.outbox_message import OutboxMessage
from messaging.domain.outbox_status import OutboxStatus

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=START):
        self.current = now

    def __call__(self):
        return self.current

    def advance(self, **delta):
        self.current += timedelta(**delta)


def event(order_id="order", event_type="OrderAllocated"):
    return IntegrationEvent("owner", "order", order_id, event_type, {"order_id": order_id})


def pending(order_id="order", created_at=START, **changes):
    message = OutboxMessage.pending(event(order_id), created_at)
    return message if not changes else OutboxMessage(**{**message.__dict__, **changes})


class InMemoryOutbox:
    """Claims due rows in order; a failed transaction restores every row."""

    def __init__(self, *messages):
        self.rows = {m.message_id: m for m in messages}
        self.saves = 0
        self.fail_on_save = None
        self.active = False

    @contextmanager
    def __call__(self):
        assert not self.active
        snapshot = dict(self.rows)
        self.active = True
        try:
            yield self
        except BaseException:
            self.rows = snapshot
            raise
        finally:
            self.active = False

    def claim_due(self, now, limit):
        due = [m for m in self.rows.values()
               if m.status == OutboxStatus.PENDING and m.next_attempt_at <= now]
        return sorted(due, key=lambda m: (m.created_at, m.message_id))[:limit]

    def save(self, message):
        if self.fail_on_save is not None:
            raise self.fail_on_save
        self.rows[message.message_id] = message
        self.saves += 1

    def get(self, message_id):
        return self.rows[message_id]


class InMemoryInbox:
    """Inbox rows and handler effects share one snapshot, like one SQL transaction."""

    def __init__(self):
        self.seen = set()
        self.effects = []
        self.active = False

    @contextmanager
    def __call__(self):
        assert not self.active
        snapshot = (set(self.seen), list(self.effects))
        self.active = True
        try:
            yield self
        except BaseException:
            self.seen, self.effects = snapshot
            raise
        finally:
            self.active = False

    def record_inbox(self, consumer_name, message_id):
        if (consumer_name, message_id) in self.seen:
            return False
        self.seen.add((consumer_name, message_id))
        return True
