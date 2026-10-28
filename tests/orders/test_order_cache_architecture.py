"""The cache is an adapter: only infrastructure may know the client, and writes never see the port."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src"
ORDERS = ROOT / "orders"
CLIENT_LIBRARIES = {"valkey", "redis"}
CACHE_MODULES = {"order_summary_cache", "caching_order_queries", "cache_unavailable"}
# The only application modules that may know the cache port.
CACHE_AWARE = {"order_summary_cache", "caching_order_queries", "cache_unavailable",
               "invalidating_use_case"}


def imported_names(source: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(("." * node.level) + (node.module or ""))
            names += [("." * node.level) + (node.module or "") + "." + alias.name for alias in node.names]
    return names


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_inner_layers_never_import_a_cache_client(layer):
    for source in (ORDERS / layer).rglob("*.py"):
        for name in imported_names(source):
            assert name.split(".")[0] not in CLIENT_LIBRARIES, (source, name)


def test_the_cache_client_lives_only_in_orders_infrastructure():
    for source in ROOT.rglob("*.py"):
        if source.is_relative_to(ORDERS / "infrastructure"):
            continue
        for name in imported_names(source):
            assert name.split(".")[0] not in CLIENT_LIBRARIES, (source, name)


def test_write_use_cases_cannot_reach_the_cache():
    # PostgreSQL is authoritative: anything that mutates or allocates must not even import the cache.
    for source in (ORDERS / "application").glob("*.py"):
        if source.stem in CACHE_AWARE:
            continue
        for name in imported_names(source):
            assert name.rsplit(".", 1)[-1] not in CACHE_MODULES, (source, name)
    for capability in ("inventory", "picking", "packing", "shipping", "messaging", "integrations"):
        for source in (ROOT / capability).rglob("*.py"):
            for name in imported_names(source):
                assert name.rsplit(".", 1)[-1] not in CACHE_MODULES, (source, name)
