"""Reconciliation against real PostgreSQL, including two reconcilers racing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

import pytest

from channel_support import ChannelOrderLine, at
from integration_postgres_support import PostgresLab, wait_for_checkpoint_lock_wait

LINES = (ChannelOrderLine("l1", "sku", 1),)


def place(lab, order_id, minutes, client="owner"):
    return lab.channel.upsert(client, order_id, "w1", LINES, updated_at=at(minutes))


def test_lost_webhook_is_repaired_once_and_a_delivered_one_is_not_duplicated(orders_database):
    lab = PostgresLab(orders_database)
    place(lab, "delivered", 1)
    lab.webhooks.drop = True
    place(lab, "lost", 2)
    assert lab.order_ids() == ["delivered"]
    report = lab.reconcile.execute("owner")
    assert (report.examined, report.repaired, report.already_known) == (2, 1, 1)
    assert lab.order_ids() == ["delivered", "lost"]
    assert lab.reconcile.execute("owner").repaired == 0


def test_checkpoint_is_durable_across_instances_and_never_regresses(orders_database):
    lab = PostgresLab(orders_database)
    lab.webhooks.drop = True
    place(lab, "c1", 5)
    lab.reconcile.execute("owner")
    saved = lab.checkpoint()
    assert saved is not None
    fresh = PostgresLab(orders_database)
    assert fresh.reconcile.execute("owner").repaired == 0
    assert fresh.checkpoint() == saved


def test_crash_mid_page_leaves_the_checkpoint_and_the_resume_repairs_the_rest(orders_database):
    lab = PostgresLab(orders_database, overlap=timedelta(0), page_size=2)
    lab.webhooks.drop = True
    for index in range(4):
        place(lab, f"c{index}", index + 1)
    real = lab.receive.execute

    def flaky(event):
        if event.order.channel_order_id == "c3":
            raise RuntimeError("worker died")
        return real(event)

    lab.reconcile._receiver = type("R", (), {"execute": staticmethod(flaky)})()
    report = lab.reconcile.execute("owner")
    assert (report.repaired, report.failed) == (3, 1)
    assert lab.order_ids() == ["c0", "c1", "c2"]
    assert lab.checkpoint().endswith("|c1")
    lab.reconcile._receiver = lab.receive
    resumed = lab.reconcile.execute("owner")
    assert (resumed.repaired, resumed.failed) == (1, 0)
    assert lab.order_ids() == ["c0", "c1", "c2", "c3"]
    assert lab.checkpoint().endswith("|c3")


def test_late_order_is_caught_by_the_overlap_window(orders_database):
    lab = PostgresLab(orders_database, overlap=timedelta(minutes=10))
    lab.webhooks.drop = True
    place(lab, "new", 100)
    lab.reconcile.execute("owner")
    place(lab, "late", 95)
    assert lab.reconcile.execute("owner").repaired == 1
    assert lab.order_ids() == ["late", "new"]


@pytest.mark.parametrize("checkpoint_exists", [False, True])
def test_concurrent_reconcilers_wait_on_the_checkpoint_and_do_not_double_create(
        orders_database, checkpoint_exists):
    # Cold: the uncommitted checkpoint INSERT blocks the rival. Warm: the row already
    # exists, so only SELECT ... FOR UPDATE can make the rival wait.
    lab = PostgresLab(orders_database)
    lab.webhooks.drop = True
    if checkpoint_exists:
        place(lab, "c0", 0)
        lab.reconcile.execute("owner")
    place(lab, "c1", 1)
    place(lab, "c2", 2)
    inside, release = threading.Event(), threading.Event()
    real_list = lab.channel.list_orders_updated_since
    calls = []

    def slow_list(client_id, cursor, limit):
        calls.append(1)
        page = real_list(client_id, cursor, limit)
        if len(calls) == 1:
            inside.set()
            assert release.wait(10)      # first reconciler holds the checkpoint lock
        return page

    lab.channel.list_orders_updated_since = slow_list
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lab.reconcile.execute, "owner")
        assert inside.wait(5)
        second = pool.submit(lab.reconcile.execute, "owner")
        wait_for_checkpoint_lock_wait(orders_database)
        assert not second.done()
        release.set()
        one, two = first.result(10), second.result(10)
    assert (one.repaired, one.failed) == (2, 0)
    # The loser re-read the overlap only after the winner committed: nothing repaired.
    assert (two.repaired, two.failed) == (0, 0)
    assert lab.order_ids() == (["c0"] if checkpoint_exists else []) + ["c1", "c2"]
    assert lab.checkpoint().endswith("|c2")


def test_reconciling_one_owner_leaves_other_owners_untouched(orders_database):
    lab = PostgresLab(orders_database)
    lab.webhooks.drop = True
    place(lab, "a1", 1, client="a")
    place(lab, "b1", 1, client="b")
    lab.reconcile.execute("a")
    assert lab.order_ids() == ["a1"]
    assert lab.checkpoint("b") is None
