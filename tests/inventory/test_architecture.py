"""Guard the small skeleton's static import direction, including relative imports."""

import ast
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2] / "src" / "inventory"


@pytest.mark.parametrize(
    ("layer", "allowed_layers"),
    [
        ("domain", {"domain"}),
        ("application", {"domain", "application"}),
        ("infrastructure", {"domain", "application", "infrastructure"}),
    ],
)
def test_inner_layers_only_import_stdlib_and_inward_layers(layer, allowed_layers):
    assert (ROOT / layer).is_dir()
    for source in (ROOT / layer).rglob("*.py"):
        module = ("inventory", *source.relative_to(ROOT).with_suffix("").parts)
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = module[:-node.level] if node.level else ()
                imports = [".".join((*prefix, node.module or "")).rstrip(".")]
            else:
                continue
            for name in imports:
                parts = name.split(".")
                if parts[0] == "inventory":
                    assert len(parts) > 1 and parts[1] in allowed_layers, (
                        source, name
                    )
                else:
                    assert parts[0] in sys.stdlib_module_names, (source, name)
