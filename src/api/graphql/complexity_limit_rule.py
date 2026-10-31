from collections.abc import Mapping
from typing import Any

from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    GraphQLError,
    GraphQLObjectType,
    IntValueNode,
    NullValueNode,
    OperationDefinitionNode,
    ValidationRule,
    VariableNode,
)

from .query_selection_walker import child_parts


def complexity_limit_rule(
    max_complexity: int, default_page_size: int, max_page_size: int, variables: Mapping[str, Any]
) -> type[ValidationRule]:
    class ComplexityLimit(ValidationRule):
        """Every field costs 1; a field taking `first` multiplies its subtree by its page size.

        The page size is what the resolver will return: the literal, the variable's value, the
        variable's declared default, or the configured default when `first` is omitted or null.
        A value that is not a usable integer is priced at the largest page the server accepts.
        """

        def __init__(self, context) -> None:
            super().__init__(context)
            self._fragment_costs: dict[str, int] = {}
            self._variable_defaults: dict[str, Any] = {}
            self._paged_fields = {
                name
                for type_ in context.schema.type_map.values() if isinstance(type_, GraphQLObjectType)
                for name, field in type_.fields.items() if "first" in field.args
            }

        def enter_operation_definition(self, node: OperationDefinitionNode, *_) -> None:
            self._fragment_costs = {}  # a fragment's price depends on the operation's variables
            self._variable_defaults = {
                definition.variable.name.value: definition.default_value
                for definition in node.variable_definitions or ()
            }
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

        def _multiplier(self, field: FieldNode) -> int:
            if field.name.value not in self._paged_fields:
                return 1
            for argument in field.arguments or ():
                if argument.name.value == "first":
                    return self._page_size(argument.value)
            return min(default_page_size, max_page_size)

        def _page_size(self, value) -> int:
            if isinstance(value, VariableNode):
                name = value.name.value
                if name in variables:
                    given = variables[name]
                    if given is None:
                        return min(default_page_size, max_page_size)
                    return max(given, 1) if type(given) is int else max_page_size
                declared = self._variable_defaults.get(name)
                return self._page_size(declared) if declared is not None else min(default_page_size, max_page_size)
            if isinstance(value, IntValueNode):
                return max(int(value.value), 1)
            if isinstance(value, NullValueNode):
                return min(default_page_size, max_page_size)
            return max_page_size

    return ComplexityLimit
