import strawberry
from strawberry import Info

from ..graphql_context import GraphQLContext
from ..orders.order_payload import OrderPayload
from ..orders.order_type import OrderType
from .add_package_input import AddPackageInput
from .add_package_payload import AddPackagePayload
from .package_type import PackageType


@strawberry.type
class PackingMutation:

    @strawberry.mutation(description=(
        "Adds one immutable package to a PICKED order. Idempotent: an identical retry returns the "
        "stored package; the same ID with another payload is a CONFLICT."))
    def add_package(self, info: Info[GraphQLContext, None], input: AddPackageInput) -> AddPackagePayload:
        context = info.context
        package = context.services.add_package.execute(input.to_package(context))
        return AddPackagePayload(package=PackageType.from_domain(package))

    @strawberry.mutation(description=(
        "PICKED to PACKED once packages exactly cover every picked reservation. Idempotent."))
    def finish_packing(self, info: Info[GraphQLContext, None], order_id: str) -> OrderPayload:
        context = info.context
        order = context.services.finish_packing.execute(context.order_key(order_id))
        return OrderPayload(order=OrderType.from_domain(order))
