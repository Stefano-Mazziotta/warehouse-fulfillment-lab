"""Suppressing Strawberry's logger must not hand its records to logging.lastResort (raw stderr)."""
import io
import logging

from observability.configure_logging import configure_logging


def test_suppressed_strawberry_records_reach_neither_the_json_stream_nor_raw_stderr(capsys):
    stream = io.StringIO()
    root = logging.getLogger()
    strawberry = logging.getLogger("strawberry.execution")
    before = list(root.handlers), root.level, list(strawberry.handlers), strawberry.propagate
    try:
        configure_logging(stream=stream, level="INFO")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            strawberry.error("GraphQL request:1:3\n{ order(orderId: \"secret-id\") }", exc_info=True)
    finally:
        root.handlers[:], root.level = before[0], before[1]
        strawberry.handlers[:], strawberry.propagate = before[2], before[3]
    assert stream.getvalue() == ""
    assert capsys.readouterr().err == ""
