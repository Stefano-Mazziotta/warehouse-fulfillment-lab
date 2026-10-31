from sqlalchemy import Engine

from integrations.application.receive_channel_event import ReceiveChannelEvent
from integrations.infrastructure.postgres_ingest_transaction import PostgresIngestTransaction
from inventory.application.get_inventory import GetInventory
from inventory.infrastructure.postgres_inventory_repository import PostgresInventoryRepository
from orders.application.allocate_order import AllocateOrder
from orders.application.cancel_order import CancelOrder
from orders.application.create_order import CreateOrder
from orders.application.get_order import GetOrder
from orders.application.get_order_summary import GetOrderSummary
from orders.application.list_orders import ListOrders
from orders.infrastructure.postgres_order_queries import PostgresOrderQueries
from orders.infrastructure.postgres_order_transaction import PostgresOrderTransaction
from packing.application.add_package import AddPackage
from packing.application.finish_packing import FinishPacking
from packing.infrastructure.postgres_package_queries import PostgresPackageQueries
from picking.application.complete_picking import CompletePicking
from picking.application.record_pick import RecordPick
from picking.application.start_picking import StartPicking
from shipping.application.reconcile_shipment import ReconcileShipment
from shipping.application.ship_order import ShipOrder
from shipping.infrastructure.postgres_attempt_queries import PostgresAttemptQueries
from shipping.infrastructure.postgres_fake_carrier import PostgresFakeCarrier

from .api_services import ApiServices
from .app_config import AppConfig


def compose_services(engine: Engine, config: AppConfig) -> ApiServices:
    """The one place that picks adapters. Each use case gets a fresh transaction per call."""
    transaction = lambda: PostgresOrderTransaction(engine)  # noqa: E731
    if config.install_lab_fakes:
        PostgresFakeCarrier.install(engine)
    carrier = PostgresFakeCarrier(engine)
    order_queries = PostgresOrderQueries(engine)
    return ApiServices(
        create_order=CreateOrder(transaction),
        allocate_order=AllocateOrder(transaction),
        cancel_order=CancelOrder(transaction),
        get_order=GetOrder(transaction),
        get_order_summary=GetOrderSummary(order_queries),
        list_orders=ListOrders(order_queries),
        start_picking=StartPicking(transaction),
        record_pick=RecordPick(transaction),
        complete_picking=CompletePicking(transaction),
        add_package=AddPackage(transaction),
        finish_packing=FinishPacking(transaction),
        ship_order=ShipOrder(transaction, carrier),
        reconcile_shipment=ReconcileShipment(transaction, carrier),
        get_inventory=GetInventory(PostgresInventoryRepository(engine)),
        receive_channel_event=ReceiveChannelEvent(
            lambda: PostgresIngestTransaction(engine), config.channel_source),
        order_queries=order_queries,
        package_queries=PostgresPackageQueries(engine),
        attempt_queries=PostgresAttemptQueries(engine),
    )
