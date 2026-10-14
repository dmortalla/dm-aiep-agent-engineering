"""Strict process-local resource settings; no environment or credential reads."""

from dataclasses import dataclass
from math import isfinite

from module10_ai.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Bound workers, pending work, execution time, and cached results."""

    max_workers: int = 4
    queue_capacity: int = 32
    job_timeout_seconds: float = 5.0
    cache_capacity: int = 128
    cache_ttl_seconds: float = 60.0

    def __post_init__(self) -> None:
        """Reject coercion and resource settings outside supported finite bounds."""
        for value, upper in (
            (self.max_workers, 32),
            (self.queue_capacity, 1024),
            (self.cache_capacity, 4096),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ConfigurationError("Execution capacity is outside its integer bounds.")
        for value, lower, upper in (
            (self.job_timeout_seconds, 0.01, 30),
            (self.cache_ttl_seconds, 0.01, 3600),
        ):
            if (
                type(value) not in (int, float)
                or not isfinite(value)
                or not lower <= value <= upper
            ):
                raise ConfigurationError("Execution duration is outside its finite bounds.")
