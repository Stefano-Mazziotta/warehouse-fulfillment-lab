"""Failures reported by inventory application use cases."""


class InventoryNotFound(LookupError):
    """No balance exists for the requested stock identity."""
