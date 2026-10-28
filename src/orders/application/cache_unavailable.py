class CacheUnavailable(Exception):
    """The cache could not answer (down, slow, refused). Callers fall back to the source of truth."""
