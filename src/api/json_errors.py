import logging
import uuid

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

REQUEST_ID_HEADER = "X-Request-ID"
INTERNAL_MESSAGE = "Internal server error"

_log = logging.getLogger("api.errors")

_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
}


def register_json_errors(app: Flask) -> None:
    """One JSON error envelope for every non-GraphQL failure.

    HTTP errors keep their status and headers (for example `Allow` on a 405). Anything
    else is logged with its traceback and the request ID, and the client only gets a
    generic message, so internals never leave the process.
    """

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> Response:
        request_id = _request_id()
        response = jsonify(error={
            "code": _CODES.get(error.code or 500, "HTTP_ERROR"),
            "message": error.description,
            "requestId": request_id,
        })
        response.status_code = error.code or 500
        for name, value in error.get_headers():
            if name.lower() not in {"content-type", "content-length"}:
                response.headers[name] = value
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception) -> Response:
        request_id = _request_id()
        _log.error(
            "Unhandled error on %s %s", request.method, request.path,
            exc_info=error, extra={"request_id": request_id})
        response = jsonify(error={
            "code": "INTERNAL", "message": INTERNAL_MESSAGE, "requestId": request_id})
        response.status_code = 500
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _request_id() -> str:
    return request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
