import logging
import sys
from typing import TextIO

from .json_formatter import JsonFormatter

# Marks the handler we installed, so calling configure twice replaces it instead of doubling lines.
_OWNED = "_lab_json_handler"


def configure_logging(stream: TextIO | None = None, level: str = "INFO") -> None:
    """Process-edge setup: JSON lines on stderr, nothing else.

    stderr is the whole contract: the process neither knows nor cares what collects it
    (here a file redirected by the shell and tailed by Alloy).
    """
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _OWNED, False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _OWNED, True)
    root.addHandler(handler)
    root.setLevel(level.upper())
    # We log unexpected GraphQL errors ourselves (with the request id); Strawberry's own
    # record of the same exception would double every incident. A logger with no handler and
    # propagation off falls back to logging.lastResort (raw stderr, query text and all), so
    # it gets a NullHandler: the record is swallowed on purpose.
    strawberry = logging.getLogger("strawberry.execution")
    strawberry.propagate = False
    if not any(isinstance(h, logging.NullHandler) for h in strawberry.handlers):
        strawberry.addHandler(logging.NullHandler())
