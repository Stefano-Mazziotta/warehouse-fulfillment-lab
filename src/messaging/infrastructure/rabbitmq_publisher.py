import pika
from pika.exceptions import AMQPError, ChannelError

from messaging.application.publish_failed import PublishFailed
from messaging.domain.outbox_message import OutboxMessage

from .rabbitmq_connection import connection_parameters
from .rabbitmq_message import encode
from .rabbitmq_topology import RabbitMqTopology


class RabbitMqPublisher:
    """Publish with confirms and the mandatory flag, so success means the broker kept it.

    Confirms catch a broker that refuses (nack) or loses the message; `mandatory` catches
    a message no queue wants, which would otherwise be dropped silently. Both, like every
    connection problem, surface as PublishFailed so the relay backs off and keeps the row.

    One blocking connection is reused. After any failure it is discarded and the next
    publish reconnects; a connection that idled past the heartbeat fails once, then heals.
    """

    def __init__(
        self, url: str, topology: RabbitMqTopology = RabbitMqTopology(), timeout_seconds: float = 5.0
    ) -> None:
        self._parameters = connection_parameters(url, timeout_seconds)
        self._topology = topology
        self._connection: pika.BlockingConnection | None = None
        self._channel = None

    def publish(self, message: OutboxMessage) -> None:
        try:
            channel = self._open_channel()
            channel.basic_publish(
                self._topology.exchange,
                message.event_type,
                encode(message),
                pika.BasicProperties(
                    message_id=message.message_id,
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                    headers={"event_type": message.event_type, "client_id": message.client_id},
                ),
                mandatory=True,
            )
        except pika.exceptions.UnroutableError as error:
            self._discard()
            raise PublishFailed(f"unroutable: no queue is bound for {message.event_type}") from error
        except pika.exceptions.NackError as error:
            self._discard()
            raise PublishFailed("broker nack: the message was not accepted") from error
        except (AMQPError, ChannelError, OSError) as error:
            self._discard()
            raise PublishFailed(f"{type(error).__name__}: {error}") from error

    def close(self) -> None:
        self._discard()

    def _open_channel(self):
        if self._channel is None or self._channel.is_closed or self._connection.is_closed:
            self._discard()
            self._connection = pika.BlockingConnection(self._parameters)
            self._channel = self._connection.channel()
            self._channel.confirm_delivery()
            self._topology.declare_exchange(self._channel)
        return self._channel

    def _discard(self) -> None:
        connection, self._connection, self._channel = self._connection, None, None
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except (AMQPError, OSError):
                pass  # already broken; the next publish builds a fresh connection
