"""The committed SDL makes every contract change a visible diff."""
from pathlib import Path

from strawberry.printer import print_schema

from api.app_config import AppConfig
from api.graphql.schema_factory import build_schema

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "api" / "schema.graphql"


def test_schema_matches_committed_snapshot():
    current = print_schema(build_schema(AppConfig(database_url="unused"))) + "\n"
    assert SNAPSHOT.read_text() == current, (
        "GraphQL contract changed; run `uv run python scripts/export_graphql_schema.py` and review the diff")
