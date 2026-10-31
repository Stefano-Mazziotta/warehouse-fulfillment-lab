from collections.abc import Iterator

from graphql import validate
from strawberry.extensions import SchemaExtension

from ..app_config import AppConfig
from .complexity_limit_rule import complexity_limit_rule
from .depth_limit_rule import depth_limit_rule


class QueryLimits(SchemaExtension):
    """Depth and cost validation, run as a preflight before the rest of schema validation.

    The limit rules are linear in the document size. graphql-core's default
    OverlappingFieldsCanBeMerged rule is not: a tiny fragment DAG makes it expand
    exponentially. Appending our rules to the default set does not help, because every rule
    still walks the whole document. So the limits are checked alone first, and a rejected
    document never reaches the default rules. Documents inside the limits get the normal
    validation. Created per request so the cost rule can see its variables.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def on_validate(self) -> Iterator[None]:
        context, config = self.execution_context, self._config
        rules = (
            depth_limit_rule(config.max_query_depth),
            complexity_limit_rule(
                config.max_query_complexity, config.default_page_size, config.max_page_size,
                context.variables or {}),
        )
        errors = validate(context.schema._schema, context.graphql_document, rules)
        if errors:
            # Setting this makes Strawberry skip its own validation pass for the document.
            context.pre_execution_errors = errors
        yield
