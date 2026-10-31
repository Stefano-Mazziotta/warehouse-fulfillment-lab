from sqlalchemy import Column, DateTime, Index, Integer, MetaData, Table, Text

# Separate MetaData and no foreign keys to WMS tables: the channel is an external
# system with its own storage, so it survives restarts and WMS rollbacks.
channel_metadata = MetaData()

fake_channel_orders = Table(
    "fake_channel_orders", channel_metadata,
    Column("client_id", Text, primary_key=True),
    Column("channel_order_id", Text, primary_key=True),
    Column("warehouse_id", Text, nullable=False),
    Column("lines", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Index("fake_channel_orders_by_update", "client_id", "updated_at", "channel_order_id"),
)
