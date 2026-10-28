"""A real RabbitMQ per test, isolated by uniquely named exchange and queues."""
import os
from types import SimpleNamespace
from uuid import uuid4

import pika
import pytest

from messaging.infrastructure.rabbitmq_topology import RabbitMqTopology


@pytest.fixture
def amqp_url():
    url = os.environ.get("LAB_TEST_AMQP_URL")
    if not url:
        pytest.skip("set LAB_TEST_AMQP_URL for real RabbitMQ proofs")
    return url


@pytest.fixture
def broker(amqp_url):
    suffix = uuid4().hex[:12]
    topology = RabbitMqTopology(f"lab_test.events.{suffix}")
    queues = [f"lab_test.queue.{suffix}"]
    names = SimpleNamespace(url=amqp_url, topology=topology, queue=queues[0])
    try:
        yield names
    finally:
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()
        for queue in queues:
            for name in (queue, topology.retry_queue(queue), topology.dead_letter_queue(queue)):
                channel.queue_delete(name)
        channel.exchange_delete(topology.exchange)
        connection.close()
