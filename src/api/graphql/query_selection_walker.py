from collections.abc import Iterator

from graphql import (
    FieldNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    SelectionSetNode,
    ValidationContext,
)


def child_fields(
    selection_set: SelectionSetNode | None, context: ValidationContext, visiting: frozenset[str]
) -> Iterator[tuple[FieldNode, frozenset[str]]]:
    """Fields of a selection set with fragments inlined; a fragment already on the path is skipped.

    The skip keeps a malicious fragment cycle from recursing forever before graphql-core's own
    cycle rule has reported it.
    """
    if selection_set is None:
        return
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            yield selection, visiting
        elif isinstance(selection, InlineFragmentNode):
            yield from child_fields(selection.selection_set, context, visiting)
        elif isinstance(selection, FragmentSpreadNode):
            name = selection.name.value
            fragment = context.get_fragment(name)
            if fragment is not None and name not in visiting:
                yield from child_fields(fragment.selection_set, context, visiting | {name})
