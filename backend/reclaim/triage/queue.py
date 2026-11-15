from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from ..schemas import Case, Deduction, Evidence
from .scoring import score_case


def sort_cases(cases: list[Case]) -> list[Case]:
    """Rule 5: expected value (value x win probability) desc, then earliest deadline, then id for stability.
    Cases recommended for skipping sink below workable ones."""
    return sorted(cases, key=lambda c: (c.recommend_skip, -c.expected_cents, c.deadline, c.id))


def triage(deductions: list[Deduction], today: date, history_fn=None,
           evidence_by_id: dict[str, list[Evidence]] | None = None) -> list[Case]:
    evidence_by_id = evidence_by_id or {}
    cases = []
    for d in deductions:
        pattern = f"{d.platform.value}:{d.reason.value}"
        history, scope = (0, 0), "same claim type"
        if history_fn:
            h = history_fn(pattern)
            history, scope = h if isinstance(h[0], tuple) else (h, scope)
        cases.append(score_case(d, evidence_by_id.get(d.id, []), today, history, scope))
    return sort_cases(cases)


class HeroStats(BaseModel):
    recoverable_cents: int          # expected value across workable cases
    gross_cents: int                # face value of workable cases
    workable_cases: int
    next_deadline: date | None
    next_deadline_days: int | None


def hero_stats(cases: list[Case]) -> HeroStats:
    work = [c for c in cases if not c.recommend_skip]
    nxt = min(work, key=lambda c: c.deadline) if work else None
    return HeroStats(
        recoverable_cents=sum(c.expected_cents for c in work),
        gross_cents=sum(c.recoverable_cents for c in work),
        workable_cases=len(work),
        next_deadline=nxt.deadline if nxt else None,
        next_deadline_days=nxt.days_left if nxt else None,
    )
