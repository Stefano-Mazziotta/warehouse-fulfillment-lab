"""Shared set-up: bring an order to PACKED through the real use cases, in-process."""
from sqlalchemy import Engine

from drill_context import DrillContext
from orders.application.allocate_order import AllocateOrder
from orders.application.create_order import CreateOrder
from orders.domain import Order, OrderKey, OrderLine
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction
from packing.application.add_package import AddPackage
from packing.application.finish_packing import FinishPacking
from packing.domain.package import Package
from packing.domain.package_item import PackageItem
from picking.application.complete_picking import CompletePicking
from picking.application.record_pick import RecordPick
from picking.application.start_picking import StartPicking


def transaction_factory(engine: Engine):
    return lambda: PostgresOrderTransaction(engine)


def pack_order(context: DrillContext, order_id: str, quantity: int) -> OrderKey:
    """Needs `quantity` units already received for context.ids.sku; leaves the order PACKED."""
    ids, engine = context.ids, context.engine
    key = OrderKey(ids.client_id, order_id)
    transaction = transaction_factory(engine)
    CreateOrder(transaction).execute(Order(key, ids.warehouse_id, (OrderLine(ids.line_id, ids.sku, quantity),)))
    AllocateOrder(transaction).execute(key)
    StartPicking(transaction).execute(key)
    with PostgresOrderTransaction(engine) as read:
        reservations = read.get_reservations(key)
    for reservation in reservations:
        RecordPick(transaction).execute(key, reservation.line_id, reservation.stock_key, reservation.quantity)
    CompletePicking(transaction).execute(key)
    for index, reservation in enumerate(reservations, 1):
        AddPackage(transaction).execute(Package(
            key, f"box-{index}", 900, 300, 200, 100,
            (PackageItem(key, reservation.line_id, reservation.stock_key, reservation.quantity),)))
    FinishPacking(transaction).execute(key)
    return key
