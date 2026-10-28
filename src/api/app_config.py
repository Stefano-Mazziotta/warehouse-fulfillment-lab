from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """Explicit settings; nothing reads the environment except `from_environment`."""

    database_url: str
    channel_source: str = "fake-channel"
    default_page_size: int = 20
    max_page_size: int = 50
    max_query_depth: int = 7
    max_query_complexity: int = 1000
    # The fake carrier lives outside Alembic; this creates its tables when missing.
    install_lab_fakes: bool = True

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AppConfig":
        url = environ.get("LAB_DATABASE_URL")
        if not url:
            raise RuntimeError("Set LAB_DATABASE_URL to the lab PostgreSQL URL")
        return cls(database_url=url)
