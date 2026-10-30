from collections.abc import Iterator

from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    InlineFragmentNode,
    SelectionSetNode,
    ValidationContext,
)


def child_parts(
    selection_set: SelectionSetNode | None, context: ValidationContext
) -> Iterator[FieldNode | FragmentDefinitionNode]:
    """Fields and fragment definitions directly under a selection set; inline fragments are flattened.

    A fragment is yielded as a whole instead of being expanded, so each rule can analyse it once and
    reuse the answer. Expanding it at every spread is exponential for a document in which each
    fragment spreads the previous one twice.
    """
    if selection_set is None:
        return
    for selection in selection_set.selections:
        if isinstance(selection, FieldNode):
            yield selection
        elif isinstance(selection, InlineFragmentNode):
            yield from child_parts(selection.selection_set, context)
        elif isinstance(selection, FragmentSpreadNode):
            fragment = context.get_fragment(selection.name.value)
            if fragment is not None:
                yield fragment
