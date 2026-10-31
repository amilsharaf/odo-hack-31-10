import calendar
from datetime import date, timedelta


def add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def advance(anchor: date, interval: str, n: int) -> date:
    """Start of billing period n. Always measured from the anchor, never from the previous
    period, so a monthly plan anchored on the 31st bills Jan 31, Feb 28, Mar 31 (no drift)."""
    if interval == "daily":
        return anchor + timedelta(days=n)
    if interval == "weekly":
        return anchor + timedelta(weeks=n)
    if interval == "monthly":
        return add_months(anchor, n)
    if interval == "yearly":
        return add_months(anchor, 12 * n)
    raise ValueError(f"unknown interval {interval}")


# Periods per month, used to normalise any plan to monthly recurring revenue.
PERIODS_PER_MONTH = {"daily": 365 / 12, "weekly": 52 / 12, "monthly": 1.0, "yearly": 1 / 12}
