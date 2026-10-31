"""The effect the crash drill protects: receiving stock, applied through the real inbox consumer.

Imports only application code, so the child processes that crash on purpose can use it too.
"""
from sqlalchemy import Engine, text

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.domain.inbound_message import InboundMessage
from messaging.infrastructure.postgres_inbox_transaction import PostgresInboxTransaction
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology


def stock_receipt_consumer(engine: Engine, consumer_name: str) -> IdempotentConsumer:
    """Each message adds its quantity to on_hand in the same transaction as its inbox row."""

    def handle(transaction: PostgresInboxTransaction, message: InboundMessage) -> None:
        transaction.connection.execute(
            text("UPDATE inventory_balances SET on_hand = on_hand + :quantity "
                 "WHERE client_id = :client AND sku = :sku"),
            {"quantity": message.payload["quantity"], "client": message.client_id, "sku": message.payload["sku"]})

    return IdempotentConsumer(lambda: PostgresInboxTransaction(engine), consumer_name, handle)


def runner_for(amqp_url: str, queue: str, event_type: str, consumer) -> RabbitMqConsumerRunner:
    return RabbitMqConsumerRunner(amqp_url, RabbitMqTopology(), queue, [event_type], consumer, prefetch=1)
