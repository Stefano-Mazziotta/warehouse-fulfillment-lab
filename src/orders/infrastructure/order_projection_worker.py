from collections.abc import Callable
from contextlib import AbstractContextManager

from messaging.application.idempotent_consumer import IdempotentConsumer
from messaging.application.inbox_transaction import InboxTransaction
from messaging.infrastructure.rabbitmq_consumer_runner import RabbitMqConsumerRunner
from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology
from orders.application.order_projection import OrderProjection
from orders.application.project_order_event import STAGES, ProjectOrderEvent

QUEUE = "orders.projection"
CONSUMER_NAME = "order-projection"


def build_order_projection_runner(
    transaction: Callable[[], AbstractContextManager[InboxTransaction]],
    amqp_url: str,
    projection: OrderProjection,
    *,
    topology: RabbitMqTopology = RabbitMqTopology(),
    queue: str = QUEUE,
    **runner_options,
) -> RabbitMqConsumerRunner:
    """The projection gets its own queue, so its retries and DLQ never touch another consumer.

    The queue binds every event type the projection understands, which also keeps those
    events routable for the relay's `mandatory` publishes.
    """
    consumer = IdempotentConsumer(transaction, CONSUMER_NAME, ProjectOrderEvent(projection))
    return RabbitMqConsumerRunner(
        amqp_url, topology, queue, list(STAGES), consumer, **runner_options)
