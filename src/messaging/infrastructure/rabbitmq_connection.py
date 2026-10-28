import pika


def connection_parameters(url: str, timeout_seconds: float) -> pika.URLParameters:
    # One attempt with short timeouts: the relay already owns retry and backoff, and it
    # holds row locks while we wait.
    parameters = pika.URLParameters(url)
    parameters.connection_attempts = 1
    parameters.socket_timeout = timeout_seconds
    parameters.blocked_connection_timeout = timeout_seconds
    return parameters
