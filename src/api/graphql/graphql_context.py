from dataclasses import dataclass

from orders.domain import OrderKey

from ..api_services import ApiServices
from ..app_config import AppConfig
from .invalid_input import invalid_input
from .request_loaders import RequestLoaders


@dataclass(frozen=True)
class GraphQLContext:
    """Per-request state. `client_id` comes from the X-Client-Id header (authentication stand-in)."""

    client_id: str
    services: ApiServices
    config: AppConfig
    loaders: RequestLoaders

    def order_key(self, order_id: str) -> OrderKey:
        with invalid_input():
            return OrderKey(self.client_id, order_id)
