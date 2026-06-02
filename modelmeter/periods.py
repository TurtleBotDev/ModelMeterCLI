"""Monthly reset-period calculations."""

from __future__ import annotations

import calendar
import math
from datetime import datetime, timedelta

from .models import Periods, Summary, Totals
from .sessions import add_to_breakdowns


def days_in_month(year: int, month: int) -> int:
    """Return the number of days in a month."""

    return calendar.monthrange(year, month)[1]


def period_start_for(value: datetime, reset_day: int) -> datetime:
    """Return the reset-period start that contains the given datetime."""

    day = min(reset_day, days_in_month(value.year, value.month))
    current = value.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if value >= current:
        return current
    year = value.year if value.month > 1 else value.year - 1
    month = value.month - 1 if value.month > 1 else 12
    day = min(reset_day, days_in_month(year, month))
    return value.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)


def add_period_month(value: datetime, reset_day: int) -> datetime:
    """Add one reset period month while clamping impossible month days."""

    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(reset_day, days_in_month(year, month))
    return value.replace(year=year, month=month, day=day)


def build_periods(summary: Summary, budget: int, reset_day: int, now: datetime | None = None) -> Periods:
    """Build current, previous, and all-time period totals plus pacing metrics."""

    now = now.astimezone() if now else datetime.now().astimezone()
    current_start = period_start_for(now, reset_day)
    current_end = add_period_month(current_start, reset_day)
    previous_end = current_start
    previous_start = period_start_for(current_start - timedelta(milliseconds=1), reset_day)
    current = Totals()
    previous = Totals()
    all_time = Totals()

    for request in summary.requests_list:
        add_to_breakdowns(all_time, request)
        if current_start <= request.timestamp < current_end:
            add_to_breakdowns(current, request)
        elif previous_start <= request.timestamp < previous_end:
            add_to_breakdowns(previous, request)

    elapsed = max(timedelta(), min(now, current_end) - current_start)
    period = current_end - current_start
    elapsed_fraction = elapsed / period if period.total_seconds() > 0 else 0
    expected = budget * elapsed_fraction
    used = current.credits
    elapsed_days = max(1.0, elapsed.total_seconds() / 86400)
    days_remaining = max(0, math.ceil((current_end - now).total_seconds() / 86400))

    return Periods(
        current=current,
        previous=previous,
        all_time=all_time,
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        expected_credits=expected,
        usage_balance=expected - used,
        burn_rate_per_day=used / elapsed_days,
        projected_credits=used / max(elapsed_fraction, 0.01),
        days_remaining=days_remaining,
    )


def period_totals(periods: Periods, period: str) -> Totals:
    """Return totals for a named reporting period."""

    if period == "current":
        return periods.current
    if period == "previous":
        return periods.previous
    return periods.all_time
