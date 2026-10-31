class PublishFailed(Exception):
    """The broker did not take the message; the relay will retry with backoff."""
