import base64
import binascii

from ..bad_user_input import BadUserInput

_PREFIX = "order:"


def encode_order_cursor(order_id: str) -> str:
    return base64.urlsafe_b64encode((_PREFIX + order_id).encode()).decode()


def decode_order_cursor(cursor: str) -> str:
    """Opaque to clients; a malformed cursor is a client mistake, never a server error."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, UnicodeError, ValueError):
        raise BadUserInput("Invalid cursor") from None
    if not decoded.startswith(_PREFIX) or len(decoded) == len(_PREFIX):
        raise BadUserInput("Invalid cursor")
    return decoded[len(_PREFIX):]
