"""Reconciliation behavior against a fake channel and the in-memory store."""
from datetime import timedelta

import pytest

from integrations.application.receive_channel_event import ReceiveChannelEvent
from integrations.application.reconcile_channel_orders import ReconcileChannelOrders
from integrations.domain.channel_cursor import ChannelCursor
from integrations.infrastructure.channel_webhooks import ChannelWebhooks
from integrations.infrastructure.in_memory_sales_channel import InMemorySalesChannel
from orders.domain import OrderKey

from channel_support import SOURCE, InMemoryIngestStore, at, T0, ChannelOrderLine

LINES = (ChannelOrderLine("l1", "sku", 1),)


class Harness:
    def __init__(self, page_size=50, overlap=timedelta(minutes=10)):
        self.store = InMemoryIngestStore()
        self.webhooks = ChannelWebhooks()
        self.channel = InMemorySalesChannel(self.webhooks, clock=lambda: T0)
        self.receive = ReceiveChannelEvent(self.store.transaction, SOURCE)
        self.webhooks.subscribe(self.receive.execute)
        self.reconcile = ReconcileChannelOrders(
            self.channel, self.receive, self.store.checkpoint_transaction, SOURCE,
            page_size=page_size, overlap=overlap, clock=lambda: T0)

    def place(self, order_id, minutes=0, lines=LINES, client="owner"):
        return self.channel.upsert(client, order_id, "w1", lines, updated_at=at(minutes))

    def order_ids(self):
        return sorted(key.order_id for key in self.store.orders)


@pytest.fixture
def lab():
    return Harness()


def test_lost_webhook_is_repaired_by_reconciliation_exactly_once(lab):
    lab.webhooks.drop = True
    lab.place("c1")
    assert lab.order_ids() == []
    report = lab.reconcile.execute("owner")
    assert (report.examined, report.repaired, report.already_known) == (1, 1, 0)
    assert lab.order_ids() == ["c1"]
    again = lab.reconcile.execute("owner")
    assert (again.repaired, again.already_known) == (0, 1)
    assert lab.order_ids() == ["c1"]


def test_webhook_delivered_and_reconciled_yields_one_order(lab):
    lab.place("c1")
    assert lab.order_ids() == ["c1"]
    report = lab.reconcile.execute("owner")
    assert (report.repaired, report.already_known) == (0, 1)
    assert lab.order_ids() == ["c1"]


def test_failing_webhook_handler_does_not_break_the_channel_and_reconciliation_repairs(lab):
    lab.store.fail_on = "c1"
    lab.place("c1")
    assert lab.webhooks.errors and lab.order_ids() == []
    lab.store.fail_on = None
    assert lab.reconcile.execute("owner").repaired == 1


def test_checkpoint_advances_to_the_last_order_of_a_durably_processed_page(lab):
    lab.webhooks.drop = True
    for index, minutes in enumerate((1, 2, 3)):
        lab.place(f"c{index}", minutes)
    lab.reconcile.execute("owner")
    assert lab.store.checkpoints[(SOURCE, "owner")] == ChannelCursor(at(3), "c2")


def test_pages_are_walked_to_the_end(lab):
    lab = Harness(page_size=2)
    lab.webhooks.drop = True
    for index in range(5):
        lab.place(f"c{index}", index)
    report = lab.reconcile.execute("owner")
    assert (report.examined, report.repaired) == (5, 5)
    assert lab.order_ids() == [f"c{index}" for index in range(5)]


def test_crash_mid_page_leaves_the_checkpoint_and_resume_has_no_gaps_or_duplicates():
    lab = Harness(page_size=2, overlap=timedelta(0))
    lab.webhooks.drop = True
    for index in range(4):
        lab.place(f"c{index}", index + 1)
    lab.store.fail_on = "c3"                      # second page: c2 commits, c3 fails
    report = lab.reconcile.execute("owner")
    assert (report.repaired, report.failed) == (3, 1)
    # Page 1 is durable; page 2 is not, even though c2 itself committed.
    assert lab.store.checkpoints[(SOURCE, "owner")] == ChannelCursor(at(2), "c1")
    assert lab.order_ids() == ["c0", "c1", "c2"]
    lab.store.fail_on = None
    resumed = lab.reconcile.execute("owner")
    # c1 is re-read too: even a zero overlap re-reads the checkpoint's whole instant.
    assert (resumed.repaired, resumed.failed, resumed.already_known) == (1, 0, 2)
    assert lab.order_ids() == ["c0", "c1", "c2", "c3"]


def test_overlap_window_rereads_recent_orders_without_duplicates():
    lab = Harness(overlap=timedelta(minutes=10))
    lab.webhooks.drop = True
    lab.place("c1", 100)
    lab.reconcile.execute("owner")
    report = lab.reconcile.execute("owner")
    assert (report.examined, report.already_known, report.repaired) == (1, 1, 0)
    assert lab.order_ids() == ["c1"]


def test_order_committed_late_with_an_older_timestamp_is_caught_by_the_overlap():
    lab = Harness(overlap=timedelta(minutes=10))
    lab.webhooks.drop = True
    lab.place("c-new", 100)
    lab.reconcile.execute("owner")
    lab.place("c-late", 95)       # clock skew / late commit: older than the checkpoint
    report = lab.reconcile.execute("owner")
    assert report.repaired == 1 and lab.order_ids() == ["c-late", "c-new"]


def test_without_overlap_the_late_order_is_missed_which_is_why_the_window_exists():
    lab = Harness(overlap=timedelta(0))
    lab.webhooks.drop = True
    lab.place("c-new", 100)
    lab.reconcile.execute("owner")
    lab.place("c-late", 95)
    assert lab.reconcile.execute("owner").repaired == 0
    assert lab.order_ids() == ["c-new"]


def test_conflicting_channel_data_is_reported_and_not_applied(lab):
    lab.webhooks.drop = True
    lab.place("c1", 1)
    lab.reconcile.execute("owner")
    # A channel bug: the content changes but the version does not move.
    lab.channel.rewrite_without_version_bump("owner", "c1", (ChannelOrderLine("l1", "sku", 9),))
    report = lab.reconcile.execute("owner")
    assert (report.conflicts, report.repaired) == (1, 0)
    assert lab.store.orders[OrderKey("owner", "c1")].lines[0].quantity == 1


def test_a_conflict_does_not_block_the_checkpoint_or_other_orders(lab):
    lab.webhooks.drop = True
    lab.place("c1", 1)
    lab.reconcile.execute("owner")
    lab.channel.rewrite_without_version_bump("owner", "c1", (ChannelOrderLine("l1", "sku", 9),), minutes=5)
    lab.place("c2", 6)
    report = lab.reconcile.execute("owner")
    assert (report.conflicts, report.repaired) == (1, 1)
    assert lab.store.checkpoints[(SOURCE, "owner")] == ChannelCursor(at(6), "c2")


def test_each_owner_has_its_own_checkpoint(lab):
    lab.webhooks.drop = True
    lab.place("c1", 1, client="a")
    lab.place("c2", 2, client="b")
    lab.reconcile.execute("a")
    assert (SOURCE, "b") not in lab.store.checkpoints
    assert lab.order_ids() == ["c1"]


def test_overlap_is_walked_page_by_page_not_only_on_the_first_page():
    lab = Harness(page_size=2, overlap=timedelta(minutes=10))
    lab.webhooks.drop = True
    for order_id, minutes in (("c90", 90), ("c91", 91), ("c100", 100)):
        lab.place(order_id, minutes)
    lab.reconcile.execute("owner")
    assert lab.store.checkpoints[(SOURCE, "owner")] == ChannelCursor(at(100), "c100")
    lab.place("c92", 92)
    lab.place("c95", 95)          # late arrivals inside the overlap window
    report = lab.reconcile.execute("owner")
    assert report.repaired == 2
    assert lab.order_ids() == ["c100", "c90", "c91", "c92", "c95"]
    # The checkpoint never moves backwards while re-walking the window.
    assert lab.store.checkpoints[(SOURCE, "owner")] == ChannelCursor(at(100), "c100")


def test_failure_inside_the_overlap_walk_keeps_the_checkpoint_and_the_next_run_repairs():
    lab = Harness(page_size=2, overlap=timedelta(minutes=10))
    lab.webhooks.drop = True
    for order_id, minutes in (("c90", 90), ("c91", 91), ("c100", 100)):
        lab.place(order_id, minutes)
    lab.reconcile.execute("owner")
    lab.place("c92", 92)
    lab.place("c95", 95)
    lab.store.fail_on = "c95"
    report = lab.reconcile.execute("owner")
    assert report.failed == 1
    assert lab.store.checkpoints[(SOURCE, "owner")] == ChannelCursor(at(100), "c100")
    lab.store.fail_on = None
    assert lab.reconcile.execute("owner").failed == 0
    assert lab.order_ids() == ["c100", "c90", "c91", "c92", "c95"]
