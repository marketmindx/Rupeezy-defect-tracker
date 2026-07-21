"""Time convention for the whole database: naive UTC.

Stored naive so SQLite and PostgreSQL behave identically (SQLite has no
timezone-aware column type). Convert to local time at the template layer
only — never store local times.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def utcnow() -> datetime:
    """Current UTC time with the tzinfo stripped (naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_day_start_utc(days_ago: int = 0) -> datetime:
    """The naive-UTC instant of *local* midnight, ``days_ago`` days back.

    "Today" on the dashboard means the user's local day, so day boundaries
    are computed in local time and converted for querying the UTC columns.
    """
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days_ago)
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def to_local_date(value: datetime) -> date:
    """Naive-UTC timestamp → the local calendar date it falls on."""
    return value.replace(tzinfo=timezone.utc).astimezone().date()


def local_date_start_utc(day: date) -> datetime:
    """Naive-UTC instant of *local* midnight on ``day`` (date-range filters)."""
    local_midnight = datetime.combine(day, time.min).astimezone()
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
