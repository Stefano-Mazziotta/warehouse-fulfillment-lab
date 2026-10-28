from graphql import GraphQLError, OperationDefinitionNode, ValidationContext, ValidationRule

from .query_selection_walker import child_fields


def depth_limit_rule(max_depth: int) -> type[ValidationRule]:
    class DepthLimit(ValidationRule):
        """Counts introspection too: `__schema { types { ofType ... } }` is a classic abuse."""

        def enter_operation_definition(self, node: OperationDefinitionNode, *_) -> None:
            depth = self._depth(node.selection_set, frozenset())
            if depth > max_depth:
                self.report_error(GraphQLError(
                    f"Query has depth {depth}, exceeding the maximum depth of {max_depth}",
                    nodes=[node], extensions={"code": "QUERY_TOO_DEEP"}))

        def _depth(self, selection_set, visiting: frozenset[str]) -> int:
            context: ValidationContext = self.context
            deepest = 0
            for field, inner in child_fields(selection_set, context, visiting):
                deepest = max(deepest, 1 + self._depth(field.selection_set, inner))
            return deepest

    return DepthLimit
