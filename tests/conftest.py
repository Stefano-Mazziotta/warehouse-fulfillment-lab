"""Disposable PostgreSQL schemas; never truncate shared application state."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.fixture
def drain_messaging():
    """Empty the outbox and inbox so a test can reach a migration guard that is not messaging's."""
    def drain(engine):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM outbox_messages"))
            connection.execute(text("DELETE FROM inbox_messages"))
    return drain


@pytest.fixture
def valkey_url():
    url = os.environ.get("LAB_TEST_VALKEY_URL")
    if not url:
        pytest.skip("set LAB_TEST_VALKEY_URL for real Valkey proofs")
    return url


@pytest.fixture
def dynamodb_url():
    url = os.environ.get("LAB_TEST_DYNAMODB_URL")
    if not url:
        pytest.skip("set LAB_TEST_DYNAMODB_URL for real DynamoDB Local proofs")
    return url


@pytest.fixture
def orders_database():
    url = os.environ.get("LAB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set LAB_TEST_DATABASE_URL for real PostgreSQL proofs")
    admin = create_engine(url)
    assert admin.dialect.name == "postgresql"
    schema = "lab_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={
        "options": f"-csearch_path={schema} -cstatement_timeout=10000"
    })
    try:
        with engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
