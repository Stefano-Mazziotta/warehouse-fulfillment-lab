import re
from uuid import uuid4

from observability.log_context import log_context

HEADER = "X-Request-Id"
# Ids are copied into log lines: a bounded, plain alphabet keeps a caller from forging log content.
_SAFE = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    """WSGI wrapper: one id per request, bound for every log line and echoed in the response."""

    def __init__(self, app) -> None:
        self._app = app

    def __call__(self, environ, start_response):
        supplied = environ.get("HTTP_X_REQUEST_ID", "")
        request_id = supplied if _SAFE.fullmatch(supplied) else uuid4().hex

        def start(status, headers, exc_info=None):
            return start_response(status, [*headers, (HEADER, request_id)], exc_info)

        with log_context(request_id=request_id):
            return self._app(environ, start)
