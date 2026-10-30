from collections.abc import Iterator

from strawberry.extensions import SchemaExtension

from ..app_config import AppConfig
from .complexity_limit_rule import complexity_limit_rule
from .depth_limit_rule import depth_limit_rule


class QueryLimits(SchemaExtension):
    """Adds depth and cost validation. Created per request so the cost rule can see its variables."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def on_operation(self) -> Iterator[None]:
        config = self._config
        rules = (
            depth_limit_rule(config.max_query_depth),
            complexity_limit_rule(
                config.max_query_complexity, config.default_page_size, config.max_page_size,
                self.execution_context.variables or {}),
        )
        self.execution_context.validation_rules = self.execution_context.validation_rules + rules
        yield
