"""Builders and an in-memory transaction shared by the integration proofs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from integrations.domain.channel_cursor import ChannelCursor
from integrations.domain.channel_order import ChannelOrder
from integrations.domain.channel_order_line import ChannelOrderLine
from integrations.domain.channel_order_record import ChannelOrderRecord
from orders.domain import OrderError

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
SOURCE = "fake-channel"


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def channel_order(order_id="c1", *, version=1, minutes=0, client="owner",
                  warehouse="w1", lines=(("l1", "sku", 1),)):
    return ChannelOrder(client, order_id, warehouse,
                        tuple(ChannelOrderLine(*line) for line in lines), version, at(minutes))


class InMemoryIngestStore:
    """Transactional fake: a transaction works on a copy and replaces the state on commit."""

    def __init__(self):
        self.orders, self.inbox, self.versions = {}, set(), {}
        self.events, self.checkpoints = {}, {}
        self.fail_on = None

    def transaction(self):
        return _Transaction(self)

    def checkpoint_transaction(self):
        return _CheckpointTransaction(self)


class _Transaction:
    def __init__(self, store):
        self._store = store

    def __enter__(self):
        self._work = deepcopy((self._store.orders, self._store.inbox,
                               self._store.versions, self._store.events))
        self.orders, self.inbox, self.versions, self.events = self._work
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            store = self._store
            store.orders, store.inbox, store.versions, store.events = self._work

    def record_inbox(self, consumer_name, message_id):
        if (consumer_name, message_id) in self.inbox:
            return False
        self.inbox.add((consumer_name, message_id))
        return True

    def create_order(self, order):
        if self._store.fail_on == order.key.order_id:
            raise RuntimeError("database unavailable")
        existing = self.orders.setdefault(order.key, order)
        if (existing.warehouse_id, existing.lines) != (order.warehouse_id, order.lines):
            raise OrderError("Order key already exists with a different payload")
        return existing

    def save_received_event(self, event_id, source, client_id, payload):
        self.events.setdefault(event_id, {"status": "RECEIVED", "detail": None, "payload": payload})

    def finish_event(self, event_id, status, detail):
        self.events[event_id].update(status=status.value, detail=detail)

    def lock_channel_version(self, source, client_id, channel_order_id):
        return self.versions.get((source, client_id, channel_order_id))

    def claim_channel_version(self, source, order):
        key = (source, order.client_id, order.channel_order_id)
        if key in self.versions:
            return False
        self.versions[key] = ChannelOrderRecord(order.version, order.content())
        return True

    def advance_channel_version(self, source, order):
        self.versions[(source, order.client_id, order.channel_order_id)] = ChannelOrderRecord(order.version, order.content())


class _CheckpointTransaction:
    def __init__(self, store):
        self._store = store

    def __enter__(self):
        self._staged = {}
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self._store.checkpoints.update(self._staged)

    def lock_cursor(self, source, client_id):
        return self._store.checkpoints.get((source, client_id))

    def advance(self, source, client_id, cursor, at):
        self._staged[(source, client_id)] = cursor
