"""Deadline math.

ASSUMPTION (documented, configurable): the filing window is anchored on the payout date,
the day the deduction becomes visible to the owner. DoorDash = 14 days; Uber Eats = about 30
days. Platforms' exact anchors vary, so owners should treat deadlines as conservative.
"""
from __future__ import annotations

from datetime import date, timedelta

from .schemas import Platform

DEADLINE_DAYS: dict[Platform, int] = {
    Platform.DOORDASH: 14,
    Platform.UBEREATS: 30,
    Platform.GRUBHUB: 14,
}


def filing_deadline(platform: Platform, payout_date: date) -> date:
    return payout_date + timedelta(days=DEADLINE_DAYS[platform])


def days_left(deadline: date, today: date) -> int:
    """Negative when expired."""
    return (deadline - today).days
