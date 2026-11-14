from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime

from ..schemas import ClaimReason, Deduction


@dataclass
class ParseResult:
    deductions: list[Deduction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # row-level problems, never silently dropped


def customer_key(name: str) -> str:
    """Stable hash so repeat claimants can be matched without keeping raw names (rule 10)."""
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()[:10]


def parse_dt(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised timestamp: {s!r}")


def parse_day(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def map_reason(text: str) -> ClaimReason:
    t = text.lower()
    if "missing" in t:
        return ClaimReason.MISSING_ITEM
    if "wrong" in t:
        return ClaimReason.WRONG_ITEM
    return ClaimReason.OTHER
