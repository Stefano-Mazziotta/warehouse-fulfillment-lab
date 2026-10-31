from flask import Request, Response, jsonify
from strawberry.flask.views import AsyncGraphQLView
from strawberry.schema import BaseSchema

from ..api_services import ApiServices
from ..app_config import AppConfig
from .graphql_context import GraphQLContext
from .request_loaders import RequestLoaders

CLIENT_HEADER = "X-Client-Id"


class MissingClientId(Exception):
    pass


class _ClientScopedView(AsyncGraphQLView):
    """Stand-in for authentication: trusts a header. Real deployments must verify identity."""

    def __init__(self, services: ApiServices, config: AppConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._services = services
        self._config = config

    async def get_context(self, request: Request, response: Response) -> GraphQLContext:
        client_id = request.headers.get(CLIENT_HEADER, "").strip()
        if not client_id:
            raise MissingClientId()
        return GraphQLContext(
            client_id, self._services, self._config, RequestLoaders(self._services, client_id))

    async def dispatch_request(self):
        try:
            return await super().dispatch_request()
        except MissingClientId:
            response = jsonify(errors=[{
                "message": f"The {CLIENT_HEADER} header is required",
                "extensions": {"code": "UNAUTHENTICATED"}}])
            response.status_code = 401
            return response


def create_graphql_view(schema: BaseSchema, services: ApiServices, config: AppConfig):
    return _ClientScopedView.as_view(
        "graphql", schema=schema, graphql_ide=None, services=services, config=config)
