from dataclasses import FrozenInstanceError, replace

import pytest

from inventory.domain import InventoryKey
from orders.domain import Order, OrderError, OrderKey, OrderLine, OrderStatus, Reservation
from packing.domain.package import Package
from packing.domain.package_item import PackageItem
from packing.domain.packing_config import PackingConfig

KEY = OrderKey("owner", "order")
STOCK = InventoryKey("owner", "sku", "warehouse", "bin")
ORDER = Order(KEY, "warehouse", (OrderLine("a", "sku", 3),), OrderStatus.PICKED)
RESERVATIONS = (Reservation(KEY, "a", STOCK, 3, 3),)


def item(quantity=1, **changes):
    return PackageItem(KEY, "a", STOCK, quantity, **changes)


def package(package_id="box", contents=None, **changes):
    return Package(KEY, package_id, 100, 200, 150, 100,
                   (item(),) if contents is None else contents, **changes)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1"])
@pytest.mark.parametrize(
    "field",
    ["weight_grams", "length_mm", "width_mm", "height_mm"],
)
def test_measurements_require_exact_positive_integers(field, value):
    with pytest.raises(OrderError):
        replace(package(), **{field: value})


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5])
def test_content_quantity_requires_exact_positive_integer(quantity):
    with pytest.raises(OrderError):
        item(quantity)


def test_package_is_immutable_canonical_and_nonempty():
    second = PackageItem(KEY, "b", STOCK, 1)
    assert package(contents=(second, item())) == package(contents=(item(), second))
    with pytest.raises(FrozenInstanceError):
        package().weight_grams = 200
    for contents in ((), (item(), item())):
        with pytest.raises(OrderError):
            package(contents=contents)
    for package_id in ("", " ", None):
        with pytest.raises(OrderError):
            package(package_id)


def test_split_packages_conserve_reservation_and_line_totals():
    first = package("one", (item(1),))
    second = package("two", (item(2),))
    PackingConfig(ORDER, RESERVATIONS, (first,)).validate()
    with pytest.raises(OrderError):
        PackingConfig(ORDER, RESERVATIONS, (first,)).require_complete()
    PackingConfig(ORDER, RESERVATIONS, (first, second)).require_complete()




@pytest.mark.parametrize("change", [
    {"line_id": "other"}, {"stock_key": replace(STOCK, location_id="other")},
    {"stock_key": replace(STOCK, sku="other")},
    {"stock_key": replace(STOCK, warehouse_id="other")},
    {"order_key": OrderKey("owner", "other")},
])
def test_foreign_content_rejected(change):
    content = replace(item(), **change)
    with pytest.raises(OrderError):
        PackingConfig(ORDER, RESERVATIONS, (package(contents=(content,)),)).validate()


def test_overpack_duplicate_packages_and_invalid_reservation_coverage():
    with pytest.raises(OrderError):
        PackingConfig(ORDER, RESERVATIONS, (package(contents=(item(4),)),)).validate()
    with pytest.raises(OrderError):
        PackingConfig(ORDER, RESERVATIONS, (package(), package())).validate()
    for reservations in ((), RESERVATIONS * 2, (replace(
        RESERVATIONS[0],
        quantity=2,
        picked_quantity=2,
    ),)):
        with pytest.raises(OrderError):
            PackingConfig(ORDER, reservations, (package(),)).validate()
    with pytest.raises(OrderError):
        PackingConfig(ORDER, (replace(RESERVATIONS[0], picked_quantity=1),),
                      (package(contents=(item(2),)),)).validate()
