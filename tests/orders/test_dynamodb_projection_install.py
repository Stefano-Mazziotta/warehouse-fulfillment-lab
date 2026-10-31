"""install() must not return before the table can take writes, even when someone else created it."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from orders.application.projection_unavailable import ProjectionUnavailable
from orders.domain import OrderStatus
from orders.infrastructure.dynamodb_order_projection import DynamoDbOrderProjection

from order_projection_support import update


class TableCreatedByAnotherProcess:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.describe_calls = 0
        self.meta = SimpleNamespace(client=SimpleNamespace(describe_table=self.describe_table))

    def create_table(self, **_):
        raise ClientError({"Error": {"Code": "ResourceInUseException", "Message": "exists"}}, "CreateTable")

    def describe_table(self, TableName):
        self.describe_calls += 1
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"Table": {"TableStatus": status}}


def projection_over(fake, sleeps):
    projection = DynamoDbOrderProjection(
        "http://127.0.0.1:1", ready_timeout_seconds=5.0, sleep=sleeps.append)
    projection._resource = fake
    return projection


def test_install_waits_until_a_table_being_created_elsewhere_is_active():
    fake, sleeps = TableCreatedByAnotherProcess(["CREATING", "CREATING", "ACTIVE"]), []

    projection_over(fake, sleeps).install()

    assert fake.describe_calls == 3 and len(sleeps) == 2


def test_install_gives_up_when_the_table_never_becomes_active():
    fake, sleeps = TableCreatedByAnotherProcess(["CREATING"]), []

    with pytest.raises(ProjectionUnavailable, match="ACTIVE"):
        projection_over(fake, sleeps).install()


def test_concurrent_installs_both_leave_a_usable_table(dynamodb_url):
    name = f"lab_test_{uuid4().hex}"
    installs = [DynamoDbOrderProjection(dynamodb_url, table_name=name) for _ in range(4)]
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda p: (p.install(), p.apply(update("ALLOCATED", warehouse_id="w", line_count=1))), installs))
        assert installs[0].get("owner", "o1").status == OrderStatus.ALLOCATED
    finally:
        installs[0].drop()
