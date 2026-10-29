"""Drill 6: a webhook is lost and reconciliation repairs it."""
from demo_format import render_table
from drill_context import DrillContext
from drill_core import Check, Drill, Explanation, Outcome
from integrations.application.receive_channel_event import ReceiveChannelEvent
from integrations.application.reconcile_channel_orders import ReconcileChannelOrders
from integrations.domain.channel_order_line import ChannelOrderLine
from integrations.infrastructure.channel_webhooks import ChannelWebhooks
from integrations.infrastructure.postgres_fake_sales_channel import PostgresFakeSalesChannel
from integrations.infrastructure.postgres_ingest_transaction import PostgresIngestTransaction
from integrations.infrastructure.postgres_reconciliation_transaction import PostgresReconciliationTransaction

SOURCE = "fake-channel"


def act(context: DrillContext) -> Outcome:
    ids, engine, say, truth = context.ids, context.engine, context.say, context.truth
    webhooks = ChannelWebhooks()
    channel = PostgresFakeSalesChannel(engine, webhooks)
    receive = ReceiveChannelEvent(lambda: PostgresIngestTransaction(engine), SOURCE)
    webhooks.subscribe(receive.execute)
    reconcile = ReconcileChannelOrders(channel, receive, lambda: PostgresReconciliationTransaction(engine), SOURCE)

    def place(label: str, *, delivered: bool) -> str:
        webhooks.drop = not delivered
        order_id = ids.order(label)
        channel.upsert(ids.client_id, order_id, ids.warehouse_id, [ChannelOrderLine(ids.line_id, ids.sku, 1)])
        return order_id

    def counts() -> dict:
        return {
            "channel orders": truth.scalar("SELECT count(*) FROM fake_channel_orders WHERE client_id = :c", c=ids.client_id),
            "WMS orders": truth.scalar("SELECT count(*) FROM orders WHERE client_id = :c", c=ids.client_id),
        }

    def cursor() -> str | None:
        rows = truth.rows("SELECT cursor FROM integration_checkpoints WHERE source = :s AND client_id = :c", s=SOURCE, c=ids.client_id)
        return rows[0]["cursor"] if rows else None

    def run_pass(title: str):
        report = reconcile.execute(ids.client_id)
        say(f"{title}: examined {report.examined}, repaired {report.repaired}, already known {report.already_known}, "
            f"conflicts {report.conflicts}, failed {report.failed}")
        say(f"  checkpoint cursor: {cursor()}")
        return report

    place("C1", delivered=True)
    place("C2", delivered=False)
    place("C3", delivered=False)
    before = counts()
    say("the channel accepted 3 orders; the webhook of 2 of them was lost on the way")
    say(render_table(list(before), [list(before.values())]))
    say(f"checkpoint cursor before any reconciliation: {cursor()}")

    first = run_pass("reconciliation pass 1")
    after_first = counts()
    cursor_first = cursor()
    second = run_pass("reconciliation pass 2 (nothing changed)")
    after_second = counts()
    cursor_second = cursor()

    place("C4", delivered=False)
    say("another webhook is lost: order C4")
    third = run_pass("reconciliation pass 3")
    final = counts()
    cursor_third = cursor()
    say(render_table(list(final), [list(final.values())]))

    return Outcome((
        Check("before reconciliation the warehouse was missing 2 of the 3 channel orders",
              before == {"channel orders": 3, "WMS orders": 1} and cursor_first is not None),
        Check("pass 1 repaired exactly the 2 lost orders and the warehouse caught up",
              (first.repaired, first.failed, first.conflicts) == (2, 0, 0) and after_first == {"channel orders": 3, "WMS orders": 3}),
        Check("pass 2 re-read the overlap window and changed nothing (idempotent); the checkpoint stayed put",
              second.repaired == 0 and after_second == after_first and cursor_second == cursor_first),
        Check("pass 3 repaired only the new loss and the checkpoint moved forward",
              third.repaired == 1 and cursor_third is not None and cursor_third > cursor_second),
        Check("the warehouse converged on the channel: 4 orders on both sides",
              final == {"channel orders": 4, "WMS orders": 4}),
    ))


DRILL = Drill(
    6, "lost-event-reconciliation", "A lost webhook is repaired by reconciliation",
    "The sales channel is the source of truth for its orders. Three orders are placed; the webhooks for "
    "two of them are lost in transit, so the warehouse never hears about them. Later a fourth is lost too.",
    "Does the warehouse notice anything is missing by itself? What do you run to repair it, and what does "
    "a second run do when nothing is missing? What moves in the checkpoint table, and when?",
    Explanation(
        invariant="the warehouse eventually converges on the channel: events are the fast path, polling is "
                  "the safety net",
        mechanism="the reconciler locks a per-(source, client) checkpoint, pages the channel by keyset cursor "
                  "(updated_at, id) starting an overlap window BEFORE the checkpoint, feeds every order "
                  "through the same ReceiveChannelEvent path as a webhook (deterministic event ids make "
                  "re-reads inbox duplicates), and advances the checkpoint only after the whole page succeeded",
        without="a lost webhook is lost forever and nobody knows: the order never ships; a strict "
                "'updated_at > checkpoint' misses ties and late commits; advancing the checkpoint first "
                "skips orders that failed",
        trade_off="reconciliation is polling: freshness is bounded by its period, it re-reads the overlap "
                  "every run (cost grows with traffic), and the checkpoint row lock serializes runners "
                  "per client"),
    act)
