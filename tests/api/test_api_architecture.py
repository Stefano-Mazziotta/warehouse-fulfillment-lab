"""Web and GraphQL frameworks live only in the api package; the core never sees them."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
CAPABILITIES = ("inventory", "orders", "picking", "packing", "shipping", "messaging", "integrations")
WEB_FRAMEWORKS = {"flask", "strawberry", "graphql", "werkzeug", "asgiref"}


def imported_roots(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield (node.module or "").split(".")[0]


def test_no_capability_layer_imports_a_web_framework():
    offenders = [
        (path.relative_to(SRC), root)
        for capability in CAPABILITIES
        for path in (SRC / capability).rglob("*.py")
        for root in imported_roots(path)
        if root in WEB_FRAMEWORKS
    ]
    assert offenders == []


def test_capabilities_do_not_depend_on_the_api_package():
    offenders = [
        path.relative_to(SRC)
        for capability in CAPABILITIES
        for path in (SRC / capability).rglob("*.py")
        if "api" in imported_roots(path)
    ]
    assert offenders == []


def test_graphql_adapters_contain_no_sql():
    offenders = [
        path.relative_to(SRC)
        for path in (SRC / "api" / "graphql").rglob("*.py")
        if {"sqlalchemy", "psycopg"} & set(imported_roots(path))
    ]
    assert offenders == []


def test_graphql_adapters_do_not_reach_into_infrastructure():
    offenders = []
    for path in (SRC / "api" / "graphql").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and "infrastructure" in node.module.split("."):
                offenders.append(path.relative_to(SRC))
    assert offenders == []
