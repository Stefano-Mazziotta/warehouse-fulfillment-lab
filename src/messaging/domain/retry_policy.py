from dataclasses import dataclass
from datetime import timedelta

from .messaging_error import MessagingError


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff: delay doubles per failure up to a cap."""

    max_attempts: int = 5
    base_delay: timedelta = timedelta(seconds=1)
    max_delay: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay <= timedelta(0) or self.max_delay < self.base_delay:
            raise MessagingError("Retry policy needs attempts >= 1 and 0 < base_delay <= max_delay")

    def delay_after(self, failures: int) -> timedelta:
        return min(self.base_delay * 2 ** (failures - 1), self.max_delay)
