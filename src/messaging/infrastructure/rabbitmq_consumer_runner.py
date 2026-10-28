from collections.abc import Callable

import pika
from pika.adapters.blocking_connection import BlockingChannel

from messaging.application.idempotent_consumer import IdempotentConsumer

from .rabbitmq_connection import connection_parameters
from .rabbitmq_message import decode
from .rabbitmq_topology import RabbitMqTopology

ATTEMPT_HEADER = "x-attempt"
ERROR_HEADER = "x-last-error"


class RabbitMqConsumerRunner:
    """Feed broker deliveries to an IdempotentConsumer with ack-after-commit.

    Order per delivery: handle (the inbox row and effects COMMIT inside it), and only then
    ack. A crash between commit and ack makes the broker redeliver; the inbox turns that
    into a no-op. That is effectively-once EFFECTS over at-least-once DELIVERY.

    A handler exception is not a reason to crash the worker. The message is republished
    to the retry queue (delay = its TTL) with x-attempt incremented, or to
    `<queue>.dlq` once max_attempts handler runs have failed, and only then is the
    original acked. If that republish fails the exception propagates, the connection
    closes and the broker redelivers the original: a duplicate is possible, a loss is not.
    Only `Exception` is treated as a handler failure.
    """

    def __init__(
        self,
        url: str,
        topology: RabbitMqTopology,
        queue: str,
        routing_keys: list[str],
        consumer: IdempotentConsumer,
        *,
        prefetch: int = 10,
        max_attempts: int = 5,
        retry_delay_ms: int = 5_000,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._parameters = connection_parameters(url, timeout_seconds)
        self._topology = topology
        self._queue = queue
        self._routing_keys = routing_keys
        self._consumer = consumer
        self._prefetch = prefetch
        self._max_attempts = max_attempts
        self._retry_delay_ms = retry_delay_ms

    def declare(self) -> None:
        connection = pika.BlockingConnection(self._parameters)
        try:
            self._declare(connection.channel())
        finally:
            connection.close()

    def run(self, should_stop: Callable[[], bool], poll_seconds: float = 1.0) -> None:
        connection = pika.BlockingConnection(self._parameters)
        try:
            channel = connection.channel()
            self._declare(channel)
            channel.confirm_delivery()
            channel.basic_qos(prefetch_count=self._prefetch)
            for method, properties, body in channel.consume(self._queue, inactivity_timeout=poll_seconds):
                if method is None:
                    if should_stop():
                        break
                    continue
                self._process(channel, method.delivery_tag, properties, body)
        finally:
            if connection.is_open:
                connection.close()

    def _declare(self, channel: BlockingChannel) -> None:
        self._topology.declare_consumer_queue(
            channel, self._queue, self._routing_keys, self._retry_delay_ms)

    def _process(self, channel: BlockingChannel, delivery_tag: int, properties, body: bytes) -> None:
        try:
            message = decode(body)
        except (ValueError, KeyError, TypeError) as error:
            # No redelivery can repair a body we cannot read: park it for a human.
            self._republish(channel, self._topology.dead_letter_queue(self._queue), properties, body,
                            attempt=0, error=f"undecodable: {error}")
        else:
            try:
                self._consumer.handle(message)  # returns only after the transaction committed
            except Exception as error:
                self._fail(channel, properties, body, error)
        channel.basic_ack(delivery_tag)

    def _fail(self, channel: BlockingChannel, properties, body: bytes, error: Exception) -> None:
        attempt = (properties.headers or {}).get(ATTEMPT_HEADER, 0) + 1
        if attempt >= self._max_attempts:
            target = self._topology.dead_letter_queue(self._queue)
        else:
            target = self._topology.retry_queue(self._queue)
        self._republish(channel, target, properties, body, attempt, f"{type(error).__name__}: {error}")

    def _republish(
        self, channel: BlockingChannel, queue: str, properties, body: bytes, attempt: int, error: str
    ) -> None:
        headers = {**(properties.headers or {}), ATTEMPT_HEADER: attempt, ERROR_HEADER: error[:500]}
        channel.basic_publish(
            "", queue, body,
            pika.BasicProperties(
                message_id=properties.message_id,
                content_type=properties.content_type,
                delivery_mode=pika.DeliveryMode.Persistent,
                headers=headers,
            ),
            mandatory=True,
        )
