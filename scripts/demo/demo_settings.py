from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

COMPOSE_PROJECT = "warehouse-fulfillment-lab"
ALLOY_PORT = 52345  # Alloy has no URL in the app's environment; this is its Compose host port.
COMPOSE_SERVICES = ("postgres", "rabbitmq", "valkey", "dynamodb-local", "loki", "alloy")


@dataclass(frozen=True)
class Settings:
    database_url: str
    amqp_url: str
    valkey_url: str
    dynamodb_url: str
    loki_url: str
    rabbitmq_management_url: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "Settings":
        # Same variable names the app and its tests use, defaulting to the Compose ports.
        return cls(
            database_url=environ.get(
                "LAB_DATABASE_URL", "postgresql+psycopg://lab:lab@127.0.0.1:55432/warehouse_lab"),
            amqp_url=environ.get("LAB_AMQP_URL", "amqp://lab:lab@127.0.0.1:55672/"),
            valkey_url=environ.get("LAB_VALKEY_URL", "valkey://127.0.0.1:56379/0"),
            dynamodb_url=environ.get("LAB_DYNAMODB_URL", "http://127.0.0.1:58000"),
            loki_url=environ.get("LAB_LOKI_URL", "http://127.0.0.1:53100"),
            rabbitmq_management_url=environ.get("LAB_RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:55673"),
        )

    def endpoints(self) -> dict[str, tuple[str, int]]:
        def of(url: str) -> tuple[str, int]:
            parsed = urlparse(url)
            return parsed.hostname or "127.0.0.1", parsed.port or 0

        return {
            "postgres": of(self.database_url), "rabbitmq": of(self.amqp_url),
            "valkey": of(self.valkey_url), "dynamodb-local": of(self.dynamodb_url),
            "loki": of(self.loki_url), "alloy": ("127.0.0.1", ALLOY_PORT),
        }


def missing_services(settings: Settings, is_open: Callable[[str, int], bool]) -> list[str]:
    return [name for name, (host, port) in settings.endpoints().items() if not is_open(host, port)]


def compose_hint(missing: list[str]) -> str:
    if not missing:
        return ""
    return f"docker compose -p {COMPOSE_PROJECT} up -d --wait {' '.join(missing)}"
