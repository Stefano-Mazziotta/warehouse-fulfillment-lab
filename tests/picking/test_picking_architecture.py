"""The picking application depends only on stdlib and inward capability ports."""

import ast
from pathlib import Path
import sys


def test_picking_has_no_framework_or_infrastructure_imports():
    root = Path(__file__).resolve().parents[2] / "src" / "picking"
    for source in root.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if parts[0] in {"inventory", "orders", "messaging"}:
                    assert len(parts) > 1 and parts[1] in {"domain", "application"}
                else:
                    assert parts[0] in sys.stdlib_module_names
