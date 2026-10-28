"""Helpers for the broker proofs: unique topology per test, raw inspection, thread runner."""
from contextlib import contextmanager
import json
import threading
import time

import pika


def wait_until(condition, timeout=10, reason="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {reason}")


@contextmanager
def raw_channel(url):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        yield connection.channel()
    finally:
        connection.close()


def queue_depth(url, queue):
    # message_count counts READY messages only; unacked ones are not included, which is
    # exactly why a closed connection must show them again once they are requeued.
    with raw_channel(url) as channel:
        return channel.queue_declare(queue, passive=True).method.message_count


def take(url, queue):
    """Read and ack one message straight from a queue; None when it is empty."""
    with raw_channel(url) as channel:
        method, properties, body = channel.basic_get(queue, auto_ack=True)
        return None if method is None else (properties, json.loads(body))


@contextmanager
def running(runner):
    stop, errors = threading.Event(), []

    def target():
        try:
            runner.run(stop.is_set, poll_seconds=0.1)
        except BaseException as error:  # surfaced to the test, not swallowed by the thread
            errors.append(error)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    try:
        yield errors
    finally:
        stop.set()
        thread.join(10)
