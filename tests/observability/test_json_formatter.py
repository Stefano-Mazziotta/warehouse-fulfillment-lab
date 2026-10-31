"""One JSON object per line: what Alloy tails and Loki indexes by content."""
import io
import json
import logging

from log_capture_support import capture_logs
from observability.configure_logging import configure_logging
from observability.log_context import log_context


def test_each_record_is_one_json_line_with_the_required_fields():
    with capture_logs() as logs:
        logging.getLogger("lab.sample").warning("something %s", "happened")
    (line,) = logs.lines
    assert set(line) >= {"timestamp", "level", "logger", "message"}
    assert (line["level"], line["logger"], line["message"]) == ("WARNING", "lab.sample", "something happened")
    assert line["timestamp"].endswith("Z")


def test_bound_context_ids_are_added_to_every_line_and_removed_afterwards():
    log = logging.getLogger("lab.sample")
    with capture_logs() as logs:
        with log_context(event_id="e1", queue="q"):
            with log_context(event_type="OrderAllocated"):
                log.info("inside")
            log.info("outer")
        log.info("outside")
    inside, outer, outside = logs.lines
    assert (inside["event_id"], inside["queue"], inside["event_type"]) == ("e1", "q", "OrderAllocated")
    assert "event_type" not in outer and outer["event_id"] == "e1"
    assert "event_id" not in outside


def test_extra_fields_are_included_but_cannot_overwrite_the_core_fields():
    with capture_logs() as logs:
        logging.getLogger("lab.sample").info("real message", extra={"attempt": 3, "level": "FAKE"})
    (line,) = logs.lines
    assert line["attempt"] == 3 and line["level"] == "INFO"


def test_exception_traceback_stays_inside_one_line():
    with capture_logs() as logs:
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("lab.sample").exception("failed")
    (line,) = logs.lines
    assert "Traceback" in line["exception"] and "ValueError: boom" in line["exception"]


def test_unserializable_values_never_break_logging():
    with capture_logs() as logs:
        logging.getLogger("lab.sample").info("x", extra={"thing": object()})
    assert "thing" in logs.lines[0]


def test_configure_logging_writes_json_to_the_given_stream_and_is_idempotent():
    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers), root.level
    try:
        configure_logging(stream=stream, level="INFO")
        configure_logging(stream=stream, level="INFO")
        logging.getLogger("lab.sample").info("once")
        logging.getLogger("lab.sample").debug("below the level")
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
        assert [line["message"] for line in lines] == ["once"]
    finally:
        root.handlers[:], root.level = before[0], before[1]
