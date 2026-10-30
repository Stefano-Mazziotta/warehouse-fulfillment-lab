from collections.abc import Mapping
from typing import Any

from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    GraphQLError,
    IntValueNode,
    OperationDefinitionNode,
    ValidationRule,
    VariableNode,
)

from .query_selection_walker import child_parts


def complexity_limit_rule(
    max_complexity: int, assumed_page_size: int, variables: Mapping[str, Any]
) -> type[ValidationRule]:
    class ComplexityLimit(ValidationRule):
        """Every field costs 1; a field taking `first` multiplies its subtree by that page size.

        A variable page size is read from the request's variables; if it is not a usable integer
        it is priced at the largest page the server would accept.
        """

        def __init__(self, context) -> None:
            super().__init__(context)
            self._fragment_costs: dict[str, int] = {}

        def enter_operation_definition(self, node: OperationDefinitionNode, *_) -> None:
            cost = self._cost_of_children(node.selection_set)
            if cost > max_complexity:
                self.report_error(GraphQLError(
                    f"Query cost {cost} exceeds the maximum of {max_complexity}; "
                    "request fewer fields or a smaller page",
                    nodes=[node], extensions={"code": "QUERY_TOO_COMPLEX"}))

        def _cost_of_children(self, selection_set) -> int:
            return sum(
                self._cost(part) if isinstance(part, FieldNode) else self._fragment_cost(part)
                for part in child_parts(selection_set, self.context)
            )

        def _cost(self, field: FieldNode) -> int:
            return 1 + self._multiplier(field) * self._cost_of_children(field.selection_set)

        def _fragment_cost(self, fragment: FragmentDefinitionNode) -> int:
            """Each fragment is priced once, so a DAG of shared fragments costs its size to walk.

            The 0 stored first doubles as the cycle guard: a fragment that reaches itself sees 0
            instead of recursing, and graphql-core's own cycle rule reports the document.
            """
            name = fragment.name.value
            if name not in self._fragment_costs:
                self._fragment_costs[name] = 0
                self._fragment_costs[name] = self._cost_of_children(fragment.selection_set)
            return self._fragment_costs[name]

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
