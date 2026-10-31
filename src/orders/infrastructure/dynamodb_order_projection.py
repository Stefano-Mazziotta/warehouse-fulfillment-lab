import time
from collections.abc import Callable

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from orders.application.order_projection import OrderProjectionUpdate, ProjectedOrder
from orders.application.projection_unavailable import ProjectionUnavailable
from orders.domain import OrderStatus

POLL_INTERVAL_SECONDS = 0.5
FACTS = ("warehouse_id", "line_count", "package_count", "tracking_number")


class DynamoDbOrderProjection:
    """One item per order: PK `OWNER#<client_id>`, SK `ORDER#<order_id>`.

    The owner is the partition key, so "one order" and "all orders of one owner" are key
    lookups (GetItem, Query) and an owner can never read another's items. Nothing here scans.

    `apply` is two idempotent writes, never a read-modify-write:
      1. facts (warehouse, line count, packages, tracking) are SET unconditionally: they are
         immutable once known, so a late event may still contribute them;
      2. status and stage are SET only if the item has no stage yet or a lower one. A
         duplicate or stale event fails that condition and changes nothing.
    A crash between the two leaves a facts-only item, which `get` treats as absent until the
    status write lands on the redelivery.
    """

    def __init__(
        self,
        url: str,
        *,
        table_name: str = "lab_order_projection",
        region: str = "us-east-1",
        timeout_seconds: float = 2.0,
        ready_timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # DynamoDB Local ignores credentials and region, but botocore insists on both.
        self._resource = boto3.resource(
            "dynamodb",
            endpoint_url=url,
            region_name=region,
            aws_access_key_id="local",
            aws_secret_access_key="local",
            config=Config(
                connect_timeout=timeout_seconds, read_timeout=timeout_seconds,
                retries={"max_attempts": 1}),
        )
        self._table = self._resource.Table(table_name)
        self._table_name = table_name
        self._ready_timeout_seconds = ready_timeout_seconds
        self._sleep = sleep

    def install(self) -> None:
        try:
            self._resource.create_table(
                TableName=self._table_name,
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                           {"AttributeName": "sk", "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                      {"AttributeName": "sk", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            ).wait_until_exists()
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceInUseException":
                raise ProjectionUnavailable(str(error)) from error
            # Another process may still be creating it: existing is not the same as writable.
            self._wait_until_active()
        except BotoCoreError as error:
            raise ProjectionUnavailable(str(error)) from error

    def _wait_until_active(self) -> None:
        # Attempt-bounded rather than clock-bounded so the wait is deterministic to test.
        attempts = max(1, int(self._ready_timeout_seconds / POLL_INTERVAL_SECONDS))
        for attempt in range(attempts):
            try:
                status = self._resource.meta.client.describe_table(
                    TableName=self._table_name)["Table"]["TableStatus"]
            except ClientError as error:
                raise ProjectionUnavailable(str(error)) from error
            if status == "ACTIVE":
                return
            if attempt < attempts - 1:
                self._sleep(POLL_INTERVAL_SECONDS)
        raise ProjectionUnavailable(
            f"Table {self._table_name} is not ACTIVE after {self._ready_timeout_seconds}s")

    def drop(self) -> None:
        try:
            self._table.delete()
            self._table.wait_until_not_exists()
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException":
                raise ProjectionUnavailable(str(error)) from error
        except BotoCoreError as error:
            raise ProjectionUnavailable(str(error)) from error

    def reset(self) -> None:
        self.drop()
        self.install()

    def apply(self, change: OrderProjectionUpdate) -> bool:
        key = self._key(change.client_id, change.order_id)
        facts = {name: getattr(change, name) for name in FACTS if getattr(change, name) is not None}
        try:
            if facts:
                names = {f"#{name}": name for name in facts}
                values = {f":{name}": value for name, value in facts.items()}
                self._table.update_item(
                    Key=key,
                    UpdateExpression="SET " + ", ".join(f"#{name} = :{name}" for name in facts),
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )
            self._table.update_item(
                Key=key,
                UpdateExpression="SET order_id = :order_id, #status = :status, stage = :stage, "
                                 "last_event_id = :event_id",
                ConditionExpression="attribute_not_exists(stage) OR stage < :stage",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":order_id": change.order_id, ":status": change.status.value,
                    ":stage": change.stage, ":event_id": change.event_id},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise ProjectionUnavailable(str(error)) from error
        except BotoCoreError as error:
            raise ProjectionUnavailable(str(error)) from error
        return True

    def get(self, client_id: str, order_id: str) -> ProjectedOrder | None:
        try:
            item = self._table.get_item(
                Key=self._key(client_id, order_id), ConsistentRead=True).get("Item")
        except (ClientError, BotoCoreError) as error:
            raise ProjectionUnavailable(str(error)) from error
        return self._view(item)

    def list_for_client(self, client_id: str) -> tuple[ProjectedOrder, ...]:
        views: list[ProjectedOrder] = []
        request = {
            "KeyConditionExpression": Key("pk").eq(self._owner(client_id)),
            "ConsistentRead": True,
        }
        try:
            while True:
                page = self._table.query(**request)
                views += [view for item in page["Items"] if (view := self._view(item))]
                if "LastEvaluatedKey" not in page:
                    return tuple(views)
                request["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        except (ClientError, BotoCoreError) as error:
            raise ProjectionUnavailable(str(error)) from error

    @staticmethod
    def _owner(client_id: str) -> str:
        return f"OWNER#{client_id}"

    def _key(self, client_id: str, order_id: str) -> dict[str, str]:
        return {"pk": self._owner(client_id), "sk": f"ORDER#{order_id}"}

    @staticmethod
    def _view(item: dict | None) -> ProjectedOrder | None:
        if item is None or "stage" not in item:
            return None
        count = lambda name: int(item[name]) if name in item else None  # noqa: E731
        return ProjectedOrder(
            item["order_id"], OrderStatus(item["status"]), item.get("warehouse_id"),
            count("line_count"), count("package_count"), item.get("tracking_number"))
