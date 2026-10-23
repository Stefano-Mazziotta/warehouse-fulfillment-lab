"""Failures caused by invalid inventory states or operations."""


class InventoryError(ValueError):
    """A requested inventory state or operation violates a domain rule."""
