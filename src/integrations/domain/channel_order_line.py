from dataclasses import dataclass

from .integrations_error import IntegrationsError


@dataclass(frozen=True)
class ChannelOrderLine:

    line_id: str
    sku: str
    quantity: int

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (self.line_id, self.sku)):
            raise IntegrationsError("Identifiers must be nonempty strings")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise IntegrationsError("Quantity must be a positive integer")
