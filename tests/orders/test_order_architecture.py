"""Resolve relative imports as well as absolute imports across capability boundaries."""

import ast
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'src' / 'orders'


@pytest.mark.parametrize('layer', ['domain', 'application'])
def test_order_inner_layers_only_depend_on_inward_layers(layer):
    allowed = {'domain'} if layer == 'domain' else {'domain', 'application'}
    for source in (ROOT / layer).rglob('*.py'):
        module = ('orders', *source.relative_to(ROOT).with_suffix('').parts)
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = module[:-node.level] if node.level else ()
                names = ['.'.join((*prefix, node.module or '')).rstrip('.')]
            else:
                continue
            for name in names:
                parts = name.split('.')
                if parts[0] == 'orders':
                    assert len(parts) > 1 and parts[1] in allowed, (source, name)
                elif parts[0] == 'inventory':
                    assert len(parts) > 1 and parts[1] == 'domain', (source, name)
                else:
                    assert parts[0] in sys.stdlib_module_names, (source, name)
