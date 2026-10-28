"""Shared wiring for API proofs: a real Flask app over a disposable PostgreSQL schema."""
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, insert

from api.api_services import ApiServices
from api.app_config import AppConfig
from api.app_factory import create_app
from api.service_composition import compose_services
from inventory.infrastructure.inventory_schema import inventory_balances
from orders.domain import Order, OrderKey, OrderLine
from packing.domain.package import Package
from packing.domain.package_item import PackageItem


def seed_stock(engine: Engine, client_id: str, sku: str, warehouse: str, **bins: int) -> None:
    with engine.begin() as connection:
        for location, quantity in bins.items():
            connection.execute(insert(inventory_balances).values(
                client_id=client_id, sku=sku, warehouse_id=warehouse, location_id=location,
                on_hand=quantity, allocated=0, picked=0, packed=0))


@dataclass
class LabApi:
    engine: Engine
    config: AppConfig
    services: ApiServices
    client: Any

    def gql(self, query: str, variables: dict | None = None, client_id: str | None = "owner") -> dict:
        headers = {} if client_id is None else {"X-Client-Id": client_id}
        response = self.client.post(
            "/graphql", json={"query": query, "variables": variables or {}}, headers=headers)
        return response.get_json()

    def ok(self, query: str, variables: dict | None = None, client_id: str = "owner") -> dict:
        body = self.gql(query, variables, client_id)
        assert "errors" not in body, body
        return body["data"]

    def error_codes(self, query: str, variables: dict | None = None, client_id: str = "owner") -> list[str]:
        body = self.gql(query, variables, client_id)
        return [error["extensions"]["code"] for error in body["errors"]]


def build_lab(engine: Engine, **config_overrides) -> LabApi:
    config = AppConfig(database_url=os.environ["LAB_TEST_DATABASE_URL"], **config_overrides)
    services = compose_services(engine, config)
    return attach(engine, config, services)


def attach(engine: Engine, config: AppConfig, services: ApiServices) -> LabApi:
    app = create_app(config, engine=engine, services=services)
    return LabApi(engine, config, services, app.test_client())


def ship_through_services(lab: LabApi, client_id: str, order_id: str, sku: str, quantity: int = 2) -> None:
    """Drive one order to SHIPPED with the use cases (not GraphQL) to seed many orders quickly."""
    services = lab.services
    key = OrderKey(client_id, order_id)
    seed_stock(lab.engine, client_id, sku, "w1", a=quantity)
    services.create_order.execute(Order(key, "w1", (OrderLine("l1", sku, quantity),)))
    services.allocate_order.execute(key)
    services.start_picking.execute(key)
    reservation = services.order_queries.reservations_for(client_id, [order_id])[order_id][0]
    services.record_pick.execute(key, reservation.line_id, reservation.stock_key, quantity)
    services.complete_picking.execute(key)
    services.add_package.execute(Package(key, "p1", 500, 100, 100, 100, (
        PackageItem(key, reservation.line_id, reservation.stock_key, quantity),)))
    services.finish_packing.execute(key)
    services.ship_order.execute(key)
