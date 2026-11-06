"""When a report is next due. Times are wall-clock times in the report's own time zone, so a
report set for 8:00 in London stays at 8:00 across daylight saving changes."""

from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


def next_run(
    frequency: str,
    *,
    hour: int,
    minute: int = 0,
    weekdays: Sequence[int] = (0,),
    day_of_month: int,
    timezone: str,
    after: datetime,
) -> datetime:
    """The first moment strictly after `after` that the schedule asks for, in UTC."""
    tz = ZoneInfo(timezone)
    today = after.astimezone(tz).date()

    def at(day):
        return datetime.combine(day, time(hour, minute), tzinfo=tz)

    if frequency == "daily":
        found = at(today)
        if found <= after:
            found = at(today + timedelta(days=1))
    elif frequency == "weekly":
        days = set(weekdays) or {0}
        # The nearest chosen day that is still ahead; a week later always has one.
        found = next(
            at(today + timedelta(days=ahead))
            for ahead in range(8)
            if (today + timedelta(days=ahead)).weekday() in days
            and at(today + timedelta(days=ahead)) > after
        )
    elif frequency == "monthly":  # the day is at most 28, so every month has it
        found = at(today.replace(day=day_of_month))
        if found <= after:
            following = (today.replace(day=1) + timedelta(days=32)).replace(day=day_of_month)
            found = at(following)
    else:
        raise ValueError(f"Unknown frequency: {frequency}")
    return found.astimezone(UTC)
