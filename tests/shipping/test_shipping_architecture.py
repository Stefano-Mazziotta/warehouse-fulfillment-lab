"""Shipping rules and orchestration stay independent of infrastructure and the carrier."""
import ast
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[2] / "src"
INNER = {"shipping", "packing", "orders", "inventory"}


def imports(source):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            yield from ((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def test_shipping_domain_and_application_have_only_inward_dependencies():
    for layer in ("domain", "application"):
        for source in (SRC / "shipping" / layer).glob("*.py"):
            for module, level in imports(source):
                parts = module.split(".")
                if level:
                    assert "infrastructure" not in parts
                elif parts[0] in INNER:
                    allowed = {"domain"} if layer == "domain" else {"domain", "application"}
                    assert len(parts) > 1 and parts[1] in allowed, (source, module)
                else:
                    assert parts[0] in sys.stdlib_module_names, (source, module)


def test_inner_capabilities_do_not_import_shipping():
    for capability in ("orders", "inventory", "packing"):
        for layer in ("domain", "application"):
            for source in (SRC / capability / layer).glob("*.py"):
                assert all(module.split(".")[0] != "shipping" for module, _ in imports(source))
