from dataclasses import dataclass

from orders.domain import OrderError, OrderKey

from .package_item import PackageItem


@dataclass(frozen=True)
class Package:

    order_key: OrderKey
    package_id: str
    weight_grams: int
    length_mm: int
    width_mm: int
    height_mm: int
    contents: tuple[PackageItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.order_key, OrderKey):
            raise OrderError("Package requires an owner-scoped order key")
        if not isinstance(self.package_id, str) or not self.package_id.strip():
            raise OrderError("Package ID must be nonempty")
        for value in (self.weight_grams, self.length_mm, self.width_mm, self.height_mm):
            if type(value) is not int or value <= 0:
                raise OrderError("Package measurements must be positive integers")
        contents = tuple(self.contents)
        if not contents or not all(isinstance(item, PackageItem) for item in contents):
            raise OrderError("Package requires nonempty valid contents")
        if any(item.order_key != self.order_key for item in contents):
            raise OrderError("Package contents must belong to its order")
        if len({item.identity for item in contents}) != len(contents):
            raise OrderError("Duplicate reservation entries are not allowed")
        object.__setattr__(self, "contents", tuple(sorted(
            contents,
            key=lambda item: item.sort_key,
        )))
