import logging
from collections.abc import Iterator

from graphql import GraphQLError
from strawberry.extensions import SchemaExtension

from .error_codes import INTERNAL, code_for

INTERNAL_MESSAGE = "Internal server error"

logger = logging.getLogger("api.errors")


class ErrorMapping(SchemaExtension):
    """Rewrites resolver failures once, after execution; resolvers just let exceptions propagate.

    The client gets a stable code and, for unexpected failures, no detail at all; the
    detail goes to the server log here, once, with the request id bound by the middleware.
    """

    def on_operation(self) -> Iterator[None]:
        yield
        result = self.execution_context.result
        if result is not None and getattr(result, "errors", None):
            result.errors = [self._map(error) for error in result.errors]

    @staticmethod
    def _map(error: GraphQLError) -> GraphQLError:
        original = error.original_error
        if original is None:  # syntax, schema validation, or a limit rule: already client-safe
            return error
        code = code_for(original)
        if code == INTERNAL:
            # Only the path and the traceback: never the query text or variables, which carry business data.
            logger.error("unhandled error in GraphQL operation", exc_info=original,
                         extra={"graphql_path": list(error.path or [])})
        return GraphQLError(
            INTERNAL_MESSAGE if code == INTERNAL else str(original),
            nodes=error.nodes,
            source=error.source,
            positions=error.positions,
            path=error.path,
            extensions={"code": code},
        )
