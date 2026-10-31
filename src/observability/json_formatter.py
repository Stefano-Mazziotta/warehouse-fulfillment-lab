import json
import logging
from datetime import datetime, timezone

from .log_context import current_log_fields

# Whatever a bare LogRecord carries is not user data; anything else came from `extra=`.
_RECORD_FIELDS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, traceback included, so a collector never has to join lines."""

    def format(self, record: logging.LogRecord) -> str:
        moment = datetime.fromtimestamp(record.created, timezone.utc)
        entry = {
            "timestamp": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = {key: value for key, value in vars(record).items() if key not in _RECORD_FIELDS}
        # Core fields win: a caller's `extra` must not be able to rewrite level or message.
        for key, value in {**current_log_fields(), **extras}.items():
            entry.setdefault(key, value)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        elif record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, default=str)
