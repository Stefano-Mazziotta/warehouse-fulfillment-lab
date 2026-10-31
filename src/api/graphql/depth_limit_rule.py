from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    GraphQLError,
    OperationDefinitionNode,
    ValidationRule,
)

from .query_selection_walker import child_parts


def depth_limit_rule(max_depth: int) -> type[ValidationRule]:
    class DepthLimit(ValidationRule):
        """Counts introspection too: `__schema { types { ofType ... } }` is a classic abuse."""

        def __init__(self, context) -> None:
            super().__init__(context)
            self._fragment_depths: dict[str, int] = {}

        def enter_operation_definition(self, node: OperationDefinitionNode, *_) -> None:
            depth = self._depth(node.selection_set)
            if depth > max_depth:
                self.report_error(GraphQLError(
                    f"Query has depth {depth}, exceeding the maximum depth of {max_depth}",
                    nodes=[node], extensions={"code": "QUERY_TOO_DEEP"}))

        def _depth(self, selection_set) -> int:
            deepest = 0
            for part in child_parts(selection_set, self.context):
                if isinstance(part, FieldNode):
                    deepest = max(deepest, 1 + self._depth(part.selection_set))
                else:
                    deepest = max(deepest, self._fragment_depth(part))
            return deepest

        def _fragment_depth(self, fragment: FragmentDefinitionNode) -> int:
            """Each fragment is measured once, so a DAG of shared fragments costs its size, not its expansion.

            The 0 stored first doubles as the cycle guard: a fragment that reaches itself sees 0
            instead of recursing, and graphql-core's own cycle rule reports the document.
            """
            name = fragment.name.value
            if name not in self._fragment_depths:
                self._fragment_depths[name] = 0
                self._fragment_depths[name] = self._depth(fragment.selection_set)
            return self._fragment_depths[name]

    return DepthLimit
