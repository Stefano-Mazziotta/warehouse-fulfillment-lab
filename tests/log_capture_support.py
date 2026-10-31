"""Capture log output exactly as the process would write it: JSON lines through the real formatter."""
import io
import json
import logging
from contextlib import contextmanager

from observability.json_formatter import JsonFormatter


class CapturedLogs:
    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream

    @property
    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self._stream.getvalue().splitlines() if line]

    def from_logger(self, name: str) -> list[dict]:
        return [line for line in self.lines if line["logger"] == name]


@contextmanager
def capture_logs(level: int = logging.DEBUG):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(level)
    try:
        yield CapturedLogs(stream)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
