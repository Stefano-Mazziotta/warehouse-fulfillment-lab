"""Packing rules and orchestration stay independent of infrastructure."""
import ast
from pathlib import Path
import sys


def test_packing_domain_and_application_have_only_inward_dependencies():
    root = Path(__file__).resolve().parents[2] / "src"
    for layer in ("domain", "application"):
        for source in (root / "packing" / layer).glob("*.py"):
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                    if node.level:
                        assert "infrastructure" not in modules[0].split(".")
                        continue
                else:
                    continue
                for module in modules:
                    parts = module.split(".")
                    if parts[0] in {"packing", "orders", "inventory", "messaging"}:
                        allowed = {"domain"} if layer == "domain" else {"domain", "application"}
                        assert len(parts) > 1 and parts[1] in allowed
                    else:
                        assert parts[0] in sys.stdlib_module_names
    for source in (root / "orders" / "domain").glob("*.py"):
        assert "packing" not in [
            node.module.split(".")[0] for node in ast.walk(ast.parse(source.read_text()))
            if isinstance(node, ast.ImportFrom) and node.module and not node.level]
