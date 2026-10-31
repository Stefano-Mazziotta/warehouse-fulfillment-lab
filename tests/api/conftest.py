import pytest

from api_support import build_adapter_lab, build_lab


@pytest.fixture
def lab(orders_database):
    return build_lab(orders_database)


@pytest.fixture
def adapter_lab():
    """Flask adapters over fake services: needs no LAB_TEST_* service."""
    return build_adapter_lab()
