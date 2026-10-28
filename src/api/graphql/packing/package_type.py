import strawberry

from packing.domain.package import Package

from .package_content_type import PackageContentType


@strawberry.type(name="Package")
class PackageType:

    package_id: str
    weight_grams: int
    length_mm: int
    width_mm: int
    height_mm: int
    contents: list[PackageContentType]

    @classmethod
    def from_domain(cls, package: Package) -> "PackageType":
        return cls(
            package_id=package.package_id, weight_grams=package.weight_grams,
            length_mm=package.length_mm, width_mm=package.width_mm, height_mm=package.height_mm,
            contents=[PackageContentType.from_domain(item) for item in package.contents])
