from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# Never mutated in place: every bind stores a new dict, so the shared default is safe.
_fields: ContextVar[Mapping[str, Any]] = ContextVar("log_fields", default={})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Attach ids to every log line written inside the block, by any logger, in this task or thread.

    A ContextVar (not a thread-local) so the ids also follow the request into the async
    GraphQL view and its resolver threads.
    """
    token = _fields.set({**_fields.get(), **fields})
    try:
        yield
    finally:
        _fields.reset(token)


def current_log_fields() -> Mapping[str, Any]:
    return _fields.get()
