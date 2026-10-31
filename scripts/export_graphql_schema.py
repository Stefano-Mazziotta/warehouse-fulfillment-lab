"""Regenerate docs/api/schema.graphql after an intentional GraphQL contract change."""
from pathlib import Path

from strawberry.printer import print_schema

from api.app_config import AppConfig
from api.graphql.schema_factory import build_schema

TARGET = Path(__file__).resolve().parents[1] / "docs" / "api" / "schema.graphql"

if __name__ == "__main__":
    TARGET.write_text(print_schema(build_schema(AppConfig(database_url="unused"))) + "\n")
    print(f"wrote {TARGET}")
