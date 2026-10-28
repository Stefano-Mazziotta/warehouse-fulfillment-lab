"""The projection store is an adapter: only orders infrastructure may import the AWS SDK."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
INFRASTRUCTURE = SRC / "orders" / "infrastructure"
AWS_SDK = {"boto3", "botocore"}


def imported_roots(source: Path):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield (node.module or "").split(".")[0]


def test_the_aws_sdk_is_confined_to_orders_infrastructure():
    sources = [s for s in SRC.rglob("*.py") if not s.is_relative_to(INFRASTRUCTURE)]
    assert sources
    for source in sources:
        assert not AWS_SDK & set(imported_roots(source)), source


def test_the_dynamodb_adapter_is_the_only_sdk_user():
    users = {s.name for s in INFRASTRUCTURE.glob("*.py") if AWS_SDK & set(imported_roots(s))}
    assert users == {"dynamodb_order_projection.py"}
