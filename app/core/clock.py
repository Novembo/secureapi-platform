from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Returns the current UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Controllable clock for tests."""

    def __init__(self, initial_time: datetime | None = None) -> None:
        self._current_time = initial_time or datetime.now(UTC)

    def now(self) -> datetime:
        return self._current_time

    def set_time(self, new_time: datetime) -> None:
        if new_time.tzinfo is None:
            new_time = new_time.replace(tzinfo=UTC)
        self._current_time = new_time

    def advance(self, **kwargs: int | float) -> None:
        from datetime import timedelta

        self._current_time += timedelta(**kwargs)


# Global clock instance (defaults to SystemClock, overridable in tests)
_global_clock: Clock = SystemClock()


def ensure_utc(dt: datetime) -> datetime:
    """Ensures datetime is timezone-aware in UTC (handles SQLite naive datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def get_clock() -> Clock:
    return _global_clock


def set_clock(clock: Clock) -> None:
    global _global_clock
    _global_clock = clock


def reset_clock() -> None:
    global _global_clock
    _global_clock = SystemClock()
