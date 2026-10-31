from sqlalchemy import Column, MetaData, Table, Text

# Deliberately a separate MetaData and no foreign keys to WMS tables: the carrier
# is an external system with its own storage and its own commit boundary.
carrier_metadata = MetaData()

fake_carrier_shipments = Table(
    "fake_carrier_shipments", carrier_metadata,
    Column("attempt_id", Text, primary_key=True),
    Column("client_id", Text, nullable=False),
    Column("order_id", Text, nullable=False),
    Column("package_ids", Text, nullable=False),
    Column("tracking_number", Text, nullable=False),
)
