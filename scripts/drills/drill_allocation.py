"""Drill 1: two workers allocate the last unit."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from demo_format import render_table
from demo_processes import wait_until
from drill_context import DrillContext
from drill_core import Check, Drill, DrillFailure, Explanation, Outcome
from drill_fulfillment import transaction_factory
from drill_verdicts import exactly_one_winner
from orders.application.allocate_order import AllocateOrder
from orders.application.create_order import CreateOrder
from orders.domain import Order, OrderError, OrderKey, OrderLine
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction

STOCK_SQL = "SELECT on_hand, allocated, on_hand - allocated AS available FROM inventory_balances " \
            "WHERE client_id = :c AND sku = :s"
WAITERS_SQL = "SELECT pid, wait_event_type AS waiting_on, left(regexp_replace(query, '^SELECT .* FROM ', 'SELECT ... FROM '), 56) AS query FROM pg_stat_activity " \
              "WHERE :holder = ANY(pg_blocking_pids(pid))"


def act(context: DrillContext) -> Outcome:
    ids, engine, say = context.ids, context.engine, context.say
    context.truth.seed_stock(ids, 1)
    keys = {name: OrderKey(ids.client_id, ids.order(name)) for name in "AB"}
    for key in keys.values():
        CreateOrder(transaction_factory(engine)).execute(
            Order(key, ids.warehouse_id, (OrderLine(ids.line_id, ids.sku, 1),)))
    stock = lambda: context.truth.rows(STOCK_SQL, c=ids.client_id, s=ids.sku)  # noqa: E731
    say("two orders (A and B) each want 1 unit; the bin holds exactly 1")
    say(render_table(["on_hand", "allocated", "available"], [list(stock()[0].values())]))

    holding, release, holder_pid = Event(), Event(), []

    class HoldingTransaction(PostgresOrderTransaction):
        """Worker A freezes right after taking the stock lock, to make the race visible."""

        def lock_stock(self, order):
            balances = super().lock_stock(order)
            holder_pid.append(self.connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            holding.set()
            release.wait(timeout=30)
            return balances

    def attempt(name: str, factory) -> tuple[bool, str]:
        try:
            AllocateOrder(factory).execute(keys[name])
            return True, "allocated"
        except OrderError as error:
            return False, str(error)

    first = second = None
    waiters: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(attempt, "A", lambda: HoldingTransaction(engine))
            if not holding.wait(15):
                raise DrillFailure("worker A never reached the stock lock")
            say(f"worker A holds the row lock on the bin (PostgreSQL backend pid {holder_pid[0]}) and has not committed")
            second = pool.submit(attempt, "B", lambda: PostgresOrderTransaction(engine))

            def blocked() -> bool:
                waiters[:] = context.truth.rows(WAITERS_SQL, holder=holder_pid[0])
                return bool(waiters)

            wait_until(blocked, 5.0, interval=0.05)
            if waiters:
                say("worker B is waiting for it:")
                say(render_table(["pid", "waiting_on", "query"], [list(row.values()) for row in waiters]))
            else:
                say("worker B was NOT blocked by worker A")
            say("a third connection meanwhile still sees A's uncommitted work as not having happened:")
            say(render_table(["on_hand", "allocated", "available"], [list(stock()[0].values())]))
            release.set()
            results = {"A": first.result(timeout=30), "B": second.result(timeout=30)}
    finally:
        release.set()

    say("results: " + "; ".join(f"worker {name}: {'WON' if won else 'lost'} ({detail})" for name, (won, detail) in results.items()))
    final = stock()[0]
    reservations = context.truth.scalar(
        "SELECT count(*) FROM order_reservations WHERE client_id = :c", c=ids.client_id)
    statuses = context.truth.rows(
        "SELECT order_id, status FROM orders WHERE client_id = :c ORDER BY order_id", c=ids.client_id)
    say(render_table(["on_hand", "allocated", "available"], [list(final.values())]))
    say(render_table(["order_id", "status"], [list(row.values()) for row in statuses]))
    say(f"reservation rows: {reservations}")
    return Outcome((
        Check("worker B was observed waiting on worker A's row lock", bool(waiters)),
        Check("exactly one of the two allocations won", exactly_one_winner([won for won, _ in results.values()])),
        Check("final stock: on_hand 1, allocated 1, available 0 (nothing oversold)",
              (final["on_hand"], final["allocated"], final["available"]) == (1, 1, 0)),
        Check("exactly one reservation row exists", reservations == 1),
    ))


DRILL = Drill(
    1, "allocation-race", "Two workers allocate the last unit",
    "SKU has exactly 1 unit available. Orders A and B each ask for it, allocated by two workers at the "
    "same moment. Worker A is frozen mid-transaction (right after locking the balance) so you can watch worker B.",
    "What does worker B do while A is frozen: read 1 available and also allocate it, fail at once, or wait? "
    "Who ends up with the unit, and what is the final available?",
    Explanation(
        invariant="allocated never exceeds on_hand: the last unit is promised to exactly one order",
        mechanism="allocation takes a row lock (SELECT ... FOR UPDATE) on the balance inside the transaction; "
                  "the second worker queues behind it and, once A commits, re-reads the committed row",
        without="both workers read available = 1 and both reserve it (a lost update): two orders promised "
                "one unit; the CHECK constraint is only a last line of defence",
        trade_off="correct but serialized: workers on a hot SKU queue behind each other (throughput and "
                  "deadlock risk, hence sorted lock order); optimistic locking would retry instead of wait"),
    act)
