import strawberry

from .package_type import PackageType


@strawberry.type(name="AddPackagePayload")
class AddPackagePayload:

    package: PackageType
