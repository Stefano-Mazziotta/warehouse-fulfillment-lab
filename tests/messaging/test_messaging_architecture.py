"""Messaging rules stay free of brokers, databases and web frameworks."""
import ast
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[2] / "src"
ROOT = SRC / "messaging"


def imported_modules(source):
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            yield from ((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def test_messaging_domain_and_application_import_no_infrastructure_libraries():
    for layer, allowed in (("domain", {"domain"}), ("application", {"domain", "application"})):
        for source in (ROOT / layer).glob("*.py"):
            for module, level in imported_modules(source):
                parts = module.split(".")
                if level:
                    assert "infrastructure" not in parts, (source, module)
                elif parts[0] == "messaging":
                    assert len(parts) > 1 and parts[1] in allowed, (source, module)
                else:
                    assert parts[0] in sys.stdlib_module_names, (source, module)


def test_messaging_core_does_not_depend_on_fulfillment_capabilities():
    # Infrastructure may share the schema metadata registry; the core may not know orders.
    forbidden = {"orders", "inventory", "picking", "packing", "shipping"}
    for layer in ("domain", "application"):
        for source in (ROOT / layer).glob("*.py"):
            assert all(module.split(".")[0] not in forbidden for module, _ in imported_modules(source))


def test_fulfillment_capabilities_publish_events_only_through_inner_messaging_layers():
    for capability in ("orders", "picking", "packing", "shipping"):
        for layer in ("domain", "application"):
            for source in (SRC / capability / layer).glob("*.py"):
                for module, _ in imported_modules(source):
                    parts = module.split(".")
                    if parts[0] == "messaging":
                        assert len(parts) > 1 and parts[1] in {"domain", "application"}, (source, module)
