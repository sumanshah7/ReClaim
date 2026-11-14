"""Deterministic scoring. The LLM never assigns probabilities; it only supplies evidence (rule 7)."""
from __future__ import annotations

from datetime import date

from ..dates import days_left, filing_deadline
from ..money import weighted_cents
from ..schemas import (Case, ClaimReason, ConfidenceReason, Deduction, Evidence, EvidenceKind)

BASE_BP = {ClaimReason.MISSING_ITEM: 5500, ClaimReason.WRONG_ITEM: 4500, ClaimReason.OTHER: 1500}
# (kind, supports) -> delta in basis points
DELTAS = {
    (EvidenceKind.TICKET_OMITS_ITEM, 1): (3000, "Claimed item is not on the order ticket"),
    (EvidenceKind.TICKET_LISTS_ITEM, 1): (1000, "Ticket lists the item, so the order was prepared as placed"),
    (EvidenceKind.PICKUP_HANDOFF, 1): (1000, "Pickup timestamp shows handoff after the order was ready"),
    (EvidenceKind.PICKUP_HANDOFF, -1): (-2000, "Pickup timestamp conflicts with the ticket"),
    (EvidenceKind.REPEAT_CLAIMANT, 1): (1200, "Several claims from the same customer account in this period"),
    (EvidenceKind.MISSING_ARTIFACT, 0): (-2500, "Key evidence is missing"),
}
P_MIN, P_MAX = 500, 9000
MIN_EXPECTED_CENTS = 500   # below $5 expected value, recommend skipping
MIN_P_BP = 2500
WEAK_CONFIDENCE_CAP = 35
PRIOR_WEIGHT = 3  # pseudo-observations behind the base rate


def blended_base(base_bp: int, won: int, total: int) -> int:
    if total <= 0:
        return base_bp
    return (base_bp * PRIOR_WEIGHT + (won * 10000 // total) * total) // (PRIOR_WEIGHT + total)


def score_case(
    d: Deduction,
    evidence: list[Evidence],
    today: date,
    history: tuple[int, int] = (0, 0),  # (won, resolved) for this reason pattern
) -> Case:
    reasons: list[ConfidenceReason] = []
    base = BASE_BP[d.reason]
    reasons.append(ConfidenceReason(text=f"Base win rate for {d.reason.value.replace('_', ' ')} claims", delta=base))
    won, total = history
    p = blended_base(base, won, total)
    if total > 0:
        reasons.append(ConfidenceReason(text=f"Prior outcomes: {won} of {total} won for this pattern", delta=p - base))

    weak = False
    for ev in evidence:
        delta, text = DELTAS.get((ev.kind, ev.supports), (0, ""))
        if not delta:
            continue
        p += delta
        reasons.append(ConfidenceReason(text=f"{text} ({ev.source_ref})", delta=delta))
        if ev.kind == EvidenceKind.MISSING_ARTIFACT:
            weak = True
    p = max(P_MIN, min(P_MAX, p))

    deadline = filing_deadline(d.platform, d.payout_date)
    left = days_left(deadline, today)
    expired = left < 0
    recoverable = 0 if expired else d.amount_cents
    expected = weighted_cents(recoverable, p)

    confidence = round(p / 100)
    if weak:
        confidence = min(confidence, WEAK_CONFIDENCE_CAP)

    skip, why = False, None
    if expired:
        skip, why = True, f"Filing deadline passed {-left} day(s) ago"
    elif p < MIN_P_BP:
        skip, why = True, "Win probability is too low to be worth the owner's time"
    elif expected < MIN_EXPECTED_CENTS:
        skip, why = True, "Expected recovery is under $5"

    return Case(
        id=d.id, deduction=d, evidence=evidence, p_win_bp=p, confidence=confidence, reasons=reasons,
        recoverable_cents=recoverable, expected_cents=expected, deadline=deadline, days_left=left,
        weak=weak, recommend_skip=skip, skip_reason=why,
    )
