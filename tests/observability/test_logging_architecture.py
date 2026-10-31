"""Logging is configured at the edge; the core may at most emit through the stdlib."""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
CAPABILITIES = ("inventory", "orders", "picking", "packing", "shipping", "messaging", "integrations")
CONFIGURATION_CALLS = {"basicConfig", "dictConfig", "fileConfig", "addHandler", "setLevel",
                       "disable", "setFormatter", "addFilter"}


def inner_layer_sources():
    return [path for capability in CAPABILITIES for layer in ("domain", "application")
            for path in (SRC / capability / layer).rglob("*.py")]


def test_inner_layers_exist_to_be_checked():
    assert len(inner_layer_sources()) > 50


@pytest.mark.parametrize("source", inner_layer_sources(), ids=lambda path: str(path.relative_to(SRC)))
def test_domain_and_application_neither_import_nor_perform_logging_configuration(source):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            roots = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            roots = [node.module or ""]
        else:
            roots = []
        assert all(name.split(".")[0] != "observability" for name in roots), (source, roots)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in CONFIGURATION_CALLS, (source, node.func.attr)


def test_only_the_edge_configures_logging():
    # Process entry points are the only non-observability callers.
    edges = {"api/app_factory.py", "orders/infrastructure/order_projection_cli.py"}
    callers = sorted(
        str(path.relative_to(SRC)) for path in SRC.rglob("*.py")
        if "configure_logging(" in path.read_text() and "observability" not in path.parts)
    assert set(callers) <= edges and "api/app_factory.py" in callers
