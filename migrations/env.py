"""Use an explicit local database URL or a caller-owned test connection."""

import os

from alembic import context
from sqlalchemy import create_engine

from inventory.infrastructure.inventory_schema import metadata
from orders.infrastructure import order_schema  # Register order tables for metadata.


def migrate(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    migrate(connection)
else:
    engine = create_engine(os.environ["LAB_DATABASE_URL"])
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()
