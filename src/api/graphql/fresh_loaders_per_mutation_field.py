from collections.abc import Callable
from typing import Any

from graphql import GraphQLResolveInfo, OperationType
from strawberry.extensions import SchemaExtension


class FreshLoadersPerMutationField(SchemaExtension):
    """Top-level mutation fields run one after another, so each starts with empty loaders.

    Without this, a field that read reservations or packages would serve those cached values to a
    later field of the same operation after a write changed them. Reads below one field still batch.
    """

    def resolve(self, _next: Callable, root: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any):
        if info.path.prev is None and info.operation.operation == OperationType.MUTATION:
            info.context.loaders.reset()
        return _next(root, info, *args, **kwargs)
