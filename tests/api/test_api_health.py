from sqlalchemy import create_engine

from api.app_config import AppConfig
from api.app_factory import create_app


def test_health_reports_database_up(lab):
    response = lab.client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_health_reports_503_when_the_database_is_unreachable():
    dead = create_engine("postgresql+psycopg://lab:lab@127.0.0.1:1/none",
                         connect_args={"connect_timeout": 1})
    app = create_app(AppConfig(database_url="unused", install_lab_fakes=False), engine=dead)
    response = app.test_client().get("/health")
    assert response.status_code == 503
    assert response.get_json() == {"status": "unavailable"}
    dead.dispose()
