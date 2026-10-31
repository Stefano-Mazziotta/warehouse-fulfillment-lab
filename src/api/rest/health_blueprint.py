from flask import Blueprint, jsonify
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


def create_health_blueprint(engine: Engine) -> Blueprint:
    blueprint = Blueprint("health", __name__)

    @blueprint.get("/health")
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok")

    return blueprint
