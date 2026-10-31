import re
from dataclasses import dataclass
from datetime import datetime

# Date digits plus four hex characters: sortable, unique per run, and safe to splice into SQL
# identifiers and log lines. Cleanup rebuilds every id from this one string.
_RUN_ID = re.compile(r"\d{10}[0-9a-f]{4}")


@dataclass(frozen=True)
class RunIds:
    run_id: str

    def __post_init__(self) -> None:
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError(f"not a demo run id: {self.run_id!r}")

    @classmethod
    def from_run_id(cls, run_id: str) -> "RunIds":
        return cls(run_id)

    @property
    def client_id(self) -> str:
        return f"demo-{self.run_id}"

    @property
    def order_id(self) -> str:
        return f"order-{self.run_id}"

    @property
    def sku(self) -> str:
        return f"SKU-{self.run_id.upper()}"

    @property
    def error_request_id(self) -> str:
        return f"demo-err-{self.run_id}"

    @property
    def error_schema(self) -> str:
        return f"lab_demo_{self.run_id}"

    line_id = "line-1"
    warehouse_id = "WH-DEMO"
    location_id = "BIN-A1"
    package_id = "box-1"


def new_run_ids(now: datetime, token: str) -> RunIds:
    return RunIds(f"{now:%m%d%H%M%S}{token}")
