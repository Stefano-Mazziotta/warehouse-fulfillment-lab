"""Integration rules stay free of databases, brokers and web frameworks."""
import ast
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[2] / "src"
ROOT = SRC / "integrations"
ALLOWED = {"integrations", "orders", "messaging"}


def imports(source):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield ("." * node.level) + (node.module or "")


def test_domain_and_application_import_only_stdlib_and_inner_layers():
    for layer in ("domain", "application"):
        for source in (ROOT / layer).glob("*.py"):
            for module in imports(source):
                if module.startswith("."):
                    assert "infrastructure" not in module, (source, module)
                    continue
                parts = module.split(".")
                if parts[0] in ALLOWED:
                    assert "infrastructure" not in parts, (source, module)
                else:
                    assert parts[0] in sys.stdlib_module_names, (source, module)


def test_domain_depends_on_nothing_outside_itself():
    for source in (ROOT / "domain").glob("*.py"):
        for module in imports(source):
            assert module.startswith(".") or module.split(".")[0] in sys.stdlib_module_names, source
