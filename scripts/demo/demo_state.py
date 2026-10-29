"""Turn raw state (PostgreSQL rows, a DynamoDB item, cache and broker counters) into readable text."""
from collections.abc import Mapping, Sequence

from demo_format import render_table

TITLES = {
    "order": "orders", "stock": "inventory_balances", "reservations": "order_reservations",
    "packages": "packages", "attempt": "shipping_attempts", "outbox": "outbox_messages",
}


def postgres_view(snapshot: Mapping, sections: Sequence[str]) -> str:
    return "\n".join(f"PostgreSQL  {TITLES[name]}\n{_indent(_section(snapshot, name))}" for name in sections)


def _section(snapshot: Mapping, name: str) -> str:
    value = snapshot[name]
    if name == "order":
        return render_table(["status"], [[value["status"]]] if value else [])
    if name == "stock":
        if not value:
            return "(no rows)"
        # `available` is computed, never stored: the table has no such column.
        return render_table(
            ["on_hand", "allocated", "picked", "available"],
            [[value["on_hand"], value["allocated"], value["picked"], value["on_hand"] - value["allocated"]]])
    if name == "attempt":
        if not value:
            return "(no shipping attempt yet)"
        return render_table(["status", "tracking_number"], [[value["status"], value["tracking_number"]]])
    columns = {
        "reservations": ["location_id", "quantity", "picked_quantity"],
        "packages": ["package_id", "weight_grams", "units"],
        "outbox": ["event_type", "status", "attempt_count"],
    }[name]
    return render_table(columns, [[row[column] for column in columns] for row in value])


def projection_view(item: Mapping | None) -> str:
    if item is None:
        return "DynamoDB    no item for this order yet"
    table = render_table(
        ["status", "stage", "package_count", "tracking_number"],
        [[item["status"], item["stage"], item.get("package_count"), item.get("tracking_number")]])
    return f"DynamoDB    lab_order_projection\n{_indent(table)}"


def cache_view(entry: Mapping, hits_delta: int | None = None) -> str:
    state = f"present, expires in {entry['ttl']}s" if entry["exists"] else "absent"
    hits = "" if hits_delta is None else f"; Valkey keyspace_hits {hits_delta:+d} during the read"
    return f"Valkey      order-summary entry: {state}{hits}"


def broker_view(stats: Mapping) -> str:
    # `processed` is the consumer's own inbox record: the broker's cumulative counters lag by seconds.
    return (f"RabbitMQ    orders.projection: ready={stats['ready']} consumers={stats['consumers']} "
            f"processed={stats['processed']} (consumer inbox rows for this client)")


def _indent(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())
