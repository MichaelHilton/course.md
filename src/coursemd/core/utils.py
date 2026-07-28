"""Utility functions for date handling and other common tasks."""

import datetime as dt
import os
import typing as t
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/New_York"
TIMEZONE_ENV_VAR = "TZ"
_SATURDAY = 5  # Monday=0, Friday=4, Saturday=5, Sunday=6


def get_timezone() -> ZoneInfo:
    """Get the configured timezone."""
    timezone_name = os.environ.get(TIMEZONE_ENV_VAR, DEFAULT_TIMEZONE)
    return ZoneInfo(timezone_name)


def set_course_timezone(timezone_name: str) -> ZoneInfo:
    """Validate and apply the configured course timezone."""
    timezone = ZoneInfo(timezone_name)
    os.environ[TIMEZONE_ENV_VAR] = timezone_name
    return timezone


def current_date() -> dt.date:
    """
    Get the current date in the configured timezone.

    Can be overridden via CURRENT_DATE_OVERRIDE environment variable for testing.
    Format: YYYY-MM-DD (e.g., "2025-01-15")
    """
    # Allow overriding the current date for testing via environment variable
    if override_date := os.environ.get("CURRENT_DATE_OVERRIDE"):
        try:
            return dt.datetime.strptime(override_date, "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError:
            # If the format is invalid, fall back to the actual current date
            pass

    timezone = get_timezone()
    return dt.datetime.now(timezone).date()


def working_days(start_date: dt.date, end_date: dt.date) -> t.Iterator[dt.date]:
    """
    Generate all working days (Mon-Fri) between start and end dates, inclusive.

    Automatically aligns to full weeks by adjusting start_date to the Monday of
    its week and end_date to the Sunday of its week.

    Args:
        start_date: The starting date
        end_date: The ending date

    Yields:
        Each working day (Monday-Friday) in the range (inclusive).
    """
    # Align to full weeks
    start_date -= dt.timedelta(days=start_date.weekday())
    end_date += dt.timedelta(days=(6 - end_date.weekday()))

    current = start_date
    while current <= end_date:
        if current.weekday() < _SATURDAY:  # Monday = 0, Friday = 4
            yield current
        current += dt.timedelta(days=1)


def week_start(day: dt.date) -> dt.date:
    """Return the Monday of the week containing ``day``."""
    return day - dt.timedelta(days=day.weekday())


def working_days_between(start: dt.date, end: dt.date) -> int:
    """
    Calculate the number of working days (Mon-Fri) between two dates, inclusive.

    Args:
        start: The starting date
        end: The ending date

    Returns:
        Number of working days between start and end (inclusive)
    """
    assert start <= end, "start date must be on or before end date"
    num_working_days = 0
    current = start
    while current <= end:
        if current.weekday() < _SATURDAY:
            num_working_days += 1
        current += dt.timedelta(days=1)
    return num_working_days
