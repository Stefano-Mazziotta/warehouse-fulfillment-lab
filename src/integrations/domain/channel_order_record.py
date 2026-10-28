from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ChannelOrderRecord:
    """The newest channel version the warehouse has accepted, and what it contained."""

    version: int
    content: Mapping[str, Any]
