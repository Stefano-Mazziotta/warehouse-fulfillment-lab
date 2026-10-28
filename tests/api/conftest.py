import pytest

from api_support import build_lab


@pytest.fixture
def lab(orders_database):
    return build_lab(orders_database)
