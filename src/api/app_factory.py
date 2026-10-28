import os

from flask import Flask
from sqlalchemy import Engine, create_engine

from .api_services import ApiServices
from .app_config import AppConfig
from .graphql.graphql_view import create_graphql_view
from .graphql.schema_factory import build_schema
from .rest.health_blueprint import create_health_blueprint
from .rest.webhook_blueprint import create_webhook_blueprint
from .service_composition import compose_services


def create_app(
    config: AppConfig,
    *,
    engine: Engine | None = None,
    services: ApiServices | None = None,
) -> Flask:
    """Composition root. `engine` and `services` are injection seams for tests.

    Flask only hosts the adapters: dependencies are passed into them, and nothing
    is stored on `g` or the app for later lookup.
    """
    engine = engine or create_engine(config.database_url, pool_pre_ping=True)
    services = services or compose_services(engine, config)
    app = Flask(__name__)
    app.json.sort_keys = False
    app.add_url_rule(
        "/graphql",
        view_func=create_graphql_view(build_schema(config), services, config),
    )
    app.register_blueprint(create_health_blueprint(engine))
    app.register_blueprint(create_webhook_blueprint(services.receive_channel_event))
    return app


def create_app_from_environment() -> Flask:
    return create_app(AppConfig.from_environment(os.environ))
