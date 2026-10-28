from dataclasses import dataclass

from inventory.application.get_inventory import GetInventory
from integrations.application.receive_channel_event import ReceiveChannelEvent
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder
from orders.application.create_order import CreateOrder
from orders.application.get_order import GetOrder
from orders.application.get_order_summary import GetOrderSummary
from orders.application.list_orders import ListOrders
from orders.application.order_queries import OrderQueries
from packing.application.add_package import AddPackage
from packing.application.finish_packing import FinishPacking
from packing.application.package_queries import PackageQueries
from picking.application.complete_picking import CompletePicking
from picking.application.record_pick import RecordPick
from picking.application.start_picking import StartPicking
from shipping.application.attempt_queries import AttemptQueries
from shipping.application.reconcile_shipment import ReconcileShipment
from shipping.application.ship_order import ShipOrder


@dataclass(frozen=True)
class ApiServices:
    """Everything the adapters may call. Handed to them explicitly, never looked up globally."""

    create_order: CreateOrder
    allocate_order: AllocateOrder
    cancel_order: CancelOrder
    get_order: GetOrder
    get_order_summary: GetOrderSummary
    list_orders: ListOrders
    start_picking: StartPicking
    record_pick: RecordPick
    complete_picking: CompletePicking
    add_package: AddPackage
    finish_packing: FinishPacking
    ship_order: ShipOrder
    reconcile_shipment: ReconcileShipment
    get_inventory: GetInventory
    receive_channel_event: ReceiveChannelEvent
    order_queries: OrderQueries
    package_queries: PackageQueries
    attempt_queries: AttemptQueries
