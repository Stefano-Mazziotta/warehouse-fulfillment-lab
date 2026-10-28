from dataclasses import dataclass

from pika.adapters.blocking_connection import BlockingChannel


@dataclass(frozen=True)
class RabbitMqTopology:
    """Every exchange, queue and binding the lab needs. Redeclaring is a no-op.

    Redeclaring with DIFFERENT arguments (for example another retry TTL) is rejected by
    the broker with PRECONDITION_FAILED: change arguments by migrating to a new queue.

    Messages that fail are never dead-lettered by the broker's own reject path. The
    consumer republishes them explicitly so it can count attempts:

        events (topic) --routing key--> <queue> --fail--> <queue>.retry --TTL expires-->
        (default exchange, routing key <queue>) --> <queue> ... --max attempts--> <queue>.dlq
    """

    exchange: str = "fulfillment.events"

    def retry_queue(self, queue: str) -> str:
        return f"{queue}.retry"

    def dead_letter_queue(self, queue: str) -> str:
        return f"{queue}.dlq"

    def declare_exchange(self, channel: BlockingChannel) -> None:
        channel.exchange_declare(self.exchange, exchange_type="topic", durable=True)

    def declare_consumer_queue(
        self, channel: BlockingChannel, queue: str, routing_keys: list[str], retry_delay_ms: int
    ) -> None:
        self.declare_exchange(channel)
        channel.queue_declare(queue, durable=True)
        for routing_key in routing_keys:
            channel.queue_bind(queue, self.exchange, routing_key)
        # An expired retry message is dead-lettered through the default exchange straight
        # back to the work queue: the TTL is the retry delay.
        channel.queue_declare(self.retry_queue(queue), durable=True, arguments={
            "x-message-ttl": retry_delay_ms,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": queue,
        })
        channel.queue_declare(self.dead_letter_queue(queue), durable=True)
