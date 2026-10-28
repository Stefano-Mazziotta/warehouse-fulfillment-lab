from collections.abc import Mapping
from typing import Any

from graphql import (
    FieldNode,
    GraphQLError,
    IntValueNode,
    OperationDefinitionNode,
    ValidationRule,
    VariableNode,
)

from .query_selection_walker import child_fields


def complexity_limit_rule(
    max_complexity: int, assumed_page_size: int, variables: Mapping[str, Any]
) -> type[ValidationRule]:
    class ComplexityLimit(ValidationRule):
        """Every field costs 1; a field taking `first` multiplies its subtree by that page size.

        A variable page size is read from the request's variables; if it is not a usable integer
        it is priced at the largest page the server would accept.
        """

        def enter_operation_definition(self, node: OperationDefinitionNode, *_) -> None:
            cost = self._cost_of_children(node.selection_set, frozenset())
            if cost > max_complexity:
                self.report_error(GraphQLError(
                    f"Query cost {cost} exceeds the maximum of {max_complexity}; "
                    "request fewer fields or a smaller page",
                    nodes=[node], extensions={"code": "QUERY_TOO_COMPLEX"}))

        def _cost_of_children(self, selection_set, visiting: frozenset[str]) -> int:
            return sum(
                self._cost(field, inner)
                for field, inner in child_fields(selection_set, self.context, visiting)
            )

        def _cost(self, field: FieldNode, visiting: frozenset[str]) -> int:
            return 1 + self._multiplier(field) * self._cost_of_children(field.selection_set, visiting)

        @staticmethod
        def _multiplier(field: FieldNode) -> int:
            for argument in field.arguments or ():
                if argument.name.value != "first":
                    continue
                if isinstance(argument.value, IntValueNode):
                    return max(int(argument.value.value), 1)
                if isinstance(argument.value, VariableNode):
                    value = variables.get(argument.value.name.value)
                    if type(value) is int:
                        return max(value, 1)
                return assumed_page_size
            return 1

    return ComplexityLimit
