"""Shipping proofs reuse the packing fixtures and run in disposable PostgreSQL schemas."""
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "packing"))

from sqlalchemy import select, text

from inventory.infrastructure.inventory_schema import inventory_balances
from orders.infrastructure.order_schema import reservations
from packing.application.add_package import AddPackage
from packing.application.finish_packing import FinishPacking
from packing_support import KEY, box, factory, prepare, wait_for_block  # noqa: F401
from shipping.application.carrier_timeout import CarrierTimeout  # noqa: F401
from shipping.infrastructure.fake_carrier_schema import fake_carrier_shipments
from shipping.infrastructure.postgres_fake_carrier import PostgresFakeCarrier
from shipping.infrastructure.shipping_schema import shipping_attempts


def prepare_packed(engine):
    reservation_rows = prepare(engine)
    for index, reservation in enumerate(reservation_rows):
        AddPackage(factory(engine)).execute(box(reservation, package_id=f"box-{index}"))
    FinishPacking(factory(engine)).execute(KEY)
    return reservation_rows


def new_carrier(engine):
    PostgresFakeCarrier.install(engine)
    return PostgresFakeCarrier(engine)


def balances(engine):
    with engine.connect() as connection:
        rows = connection.execute(select(inventory_balances).order_by("location_id")).mappings()
        return [(r["location_id"], r["on_hand"], r["allocated"], r["picked"], r["packed"])
                for r in rows]


def reserved_counts(engine):
    with engine.connect() as connection:
        return list(connection.execute(
            select(reservations.c.line_id, reservations.c.location_id,
                   reservations.c.quantity, reservations.c.picked_quantity)
            .order_by("line_id", "location_id")))


def carrier_shipments(engine):
    with engine.connect() as connection:
        return list(connection.execute(select(fake_carrier_shipments)))


def attempt_rows(engine):
    with engine.connect() as connection:
        return list(connection.execute(select(shipping_attempts)))


def order_status(engine):
    with engine.connect() as connection:
        return connection.scalar(text("select status from orders"))
