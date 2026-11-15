"""Agent tools. All are deterministic; the LLM decides which to call and weighs the results (rule 7).

Outputs are compact JSON with no absolute paths or wall-clock times so the LLM replay cache stays stable.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from ..dispute.lint import lint_dispute as _lint
from ..dispute.packet import write_packet
from ..evidence import checks
from ..ingest.normalize import load_payout as _load_payout
from ..money import fmt_cents
from ..schemas import AgentEventType, CaseStatus, Outcome, OutcomeResult
from ..triage.memory import signature_of
from .session import MAX_DRAFT_FAILURES, Session


def _j(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


def _case_view(c) -> dict:
    d = c.deduction
    return {
        "case_id": c.id, "platform": d.platform.value, "order_id": d.order_id, "amount": fmt_cents(d.amount_cents),
        "reason": d.reason.value, "claimed_item": d.claimed_item, "win_probability_pct": c.p_win_bp // 100,
        "p_win_bp": c.p_win_bp, "amount_cents": c.recoverable_cents, "expected_cents": c.expected_cents,
        "confidence": c.confidence, "expected_recovery": fmt_cents(c.expected_cents),
        "deadline": c.deadline.isoformat(), "days_left": c.days_left, "weak": c.weak,
        "recommend_skip": c.recommend_skip, "skip_reason": c.skip_reason, "status": c.status.value,
        "reasons": [r.text for r in c.reasons],
        "evidence": [{"id": e.id, "kind": e.kind.value, "supports": e.supports, "summary": e.summary,
                      "source": e.source_ref} for e in c.evidence],
    }


def build_tools(s: Session) -> dict[str, BaseTool]:
    def traced(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            try:
                out = fn(*a, **kw)
            except Exception as e:  # tools never crash the run; the agent sees a clean error
                out = _j({"ok": False, "error": f"{type(e).__name__}: {e}"})
            s.emit(AgentEventType.TOOL_CALL, {"tool": fn.__name__, "args": kw or list(a), "result": out[:300]})
            cid = kw.get("case_id") or (a[0] if a and fn.__name__ not in ("load_payout", "read_memory", "triage_cases") else None)
            if isinstance(cid, str) and cid in s.cases:
                s.trace(cid, {"tool": fn.__name__, "args": kw or list(a), "result": out})
            return out
        return inner

    @tool
    @traced
    def load_payout(path: str) -> str:
        """Parse a DoorDash or Uber Eats payout CSV and add its refund deductions to the queue.
        Returns counts and any rows that could not be parsed."""
        res = _load_payout(Path(path))
        cases = s.ingest(res.deductions)
        return _j({"ok": True, "deductions": len(res.deductions), "parse_errors": res.errors, "cases": len(cases)})

    @tool
    @traced
    def triage_cases() -> str:
        """Return the current queue, sorted by expected recovery (amount x win probability), earliest
        deadline breaking ties. Cases recommended for skipping sink to the bottom."""
        ranked = s.ranked()
        h = s.hero()
        return _j({"hero": {"expected_recoverable": fmt_cents(h.recoverable_cents), "workable_cases": h.workable_cases,
                            "next_deadline": h.next_deadline, "next_deadline_days": h.next_deadline_days},
                   "queue": [{"rank": i + 1, "case_id": c.id, "amount": fmt_cents(c.recoverable_cents),
                              "win_probability_pct": c.p_win_bp // 100, "expected": fmt_cents(c.expected_cents),
                              "days_left": c.days_left, "recommend_skip": c.recommend_skip}
                             for i, c in enumerate(ranked)]})

    @tool
    @traced
    def read_memory(reason_pattern: str) -> str:
        """Read stored outcomes for a pattern such as 'doordash:missing_item'. Returns won and resolved counts."""
        won, total = s.memory.stats(reason_pattern)
        return _j({"pattern": reason_pattern, "won": won, "resolved": total})

    @tool
    @traced
    def get_case(case_id: str) -> str:
        """Return one case with its score, written confidence reasons and all evidence so far."""
        return _j(_case_view(s.get(case_id)))

    @tool
    @traced
    def read_ticket_image(order_id: str) -> str:
        """Return what was read from the photographed order ticket (items, placed and ready times,
        reading confidence). Uses the cached extraction so the demo runs offline."""
        t = s.tickets.get(order_id)
        if t is None:
            return _j({"found": False, "order_id": order_id})
        return _j({"found": True, "order_id": order_id, "items": t.items, "ready_ts": t.ready_ts,
                   "extraction_confidence": t.extraction_confidence})

    def _evidence_result(case_id, ev):
        if ev is None:
            return _j({"ok": True, "evidence": None, "note": "nothing to record for this check"})
        change = s.add_evidence(case_id, ev)
        c = s.get(case_id)
        return _j({"ok": True, "evidence": {"id": ev.id, "kind": ev.kind.value, "supports": ev.supports,
                                            "summary": ev.summary, "source": ev.source_ref},
                   "win_probability_pct": c.p_win_bp // 100, "weak": c.weak, **change})

    @tool
    @traced
    def check_ticket_vs_claim(case_id: str) -> str:
        """Compare the item named in the refund against the order ticket. Records the finding as evidence
        and rescored the case. Reports a missing artifact if there is no readable ticket."""
        c = s.get(case_id)
        return _evidence_result(case_id, checks.check_ticket_vs_claim(c.deduction, s.tickets.get(c.deduction.order_id)))

    @tool
    @traced
    def check_pickup_timestamps(case_id: str) -> str:
        """Compare the ticket's ready time with the courier pickup time and record the result as evidence."""
        c = s.get(case_id)
        return _evidence_result(case_id, checks.check_pickup_timestamps(c.deduction, s.tickets.get(c.deduction.order_id)))

    @tool
    @traced
    def check_repeat_claimant(case_id: str) -> str:
        """Count refund claims from the same customer account on this platform in this payout period.
        Records a factual evidence item when there are three or more."""
        c = s.get(case_id)
        same = [d for d in s.deductions if d.platform == c.deduction.platform]
        return _evidence_result(case_id, checks.check_repeat_claimant(c.deduction, same))

    @tool
    @traced
    def lint_dispute(draft: str) -> str:
        """Check draft wording. Disputes must state facts and never accuse the customer."""
        problems = _lint(draft)
        return _j({"passes": not problems, "problems": problems})

    @tool
    @traced
    def submit_dispute(case_id: str, body: str, cited_evidence_ids: list[str]) -> str:
        """Submit a drafted dispute for owner approval. It is validated: wording lint, every cited
        evidence id must exist on the case and at least one must support the restaurant, and the text
        must name the order. On failure fix the listed problems and resubmit once."""
        if s.draft_failures.get(case_id, 0) >= MAX_DRAFT_FAILURES:
            return _j({"ok": False, "errors": ["retry limit reached; leave this case for manual review"]})
        errors = s.save_draft(case_id, body, cited_evidence_ids)
        return _j({"ok": not errors, "errors": errors})

    @tool
    @traced
    def send_dispute(case_id: str) -> str:
        """Send an approved dispute. Requires the owner's explicit approval. There is no platform API, so this
        writes the ready-to-submit packet and logs it as sent."""
        c = s.get(case_id)
        if case_id not in s.approved or c.status != CaseStatus.AWAITING_APPROVAL or case_id not in s.disputes:
            return _j({"ok": False, "error": "not approved by the owner; nothing was sent"})
        write_packet(s.case_dir(case_id), c, s.disputes[case_id], s.clock())
        s.cases[case_id] = c.model_copy(update={"status": CaseStatus.SENT})
        s.persist(case_id)
        d = c.deduction
        s.record_outcome(Outcome(case_id=case_id, result=OutcomeResult.PENDING, claimed_item=d.claimed_item,
                                 reason_pattern=f"{d.platform.value}:{d.reason.value}",
                                 signature=signature_of(c.evidence)))
        s.emit(AgentEventType.TODO_UPDATE, {"case_id": case_id, "status": "sent"})
        return _j({"ok": True, "sent": case_id})

    @tool
    @traced
    def recall_similar_cases(case_id: str) -> str:
        """Recall past disputes similar to this case from persistent memory: same platform and claim type,
        same evidence pattern first. Returns outcomes and the lessons recorded for them. Use this to weigh a
        case and to explain why its win probability was adjusted."""
        c = s.get(case_id)
        d = c.deduction
        pattern, sig = f"{d.platform.value}:{d.reason.value}", signature_of(c.evidence)
        (won, total), scope = s.history(pattern, sig)
        return _j({"pattern": pattern, "evidence_pattern": sig, "resolved_similar": total, "won": won, "scope": scope,
                   "cases": s.memory.similar(pattern, sig, d.claimed_item)})

    @tool
    @traced
    def record_outcome(case_id: str, result: str, recovered_cents: int = 0, lesson: str = "") -> str:
        """Store the platform's decision (won, lost or pending) so future triage learns from it. Add a short
        factual lesson (one line) when the result teaches something about similar cases. Lessons are saved to
        persistent memory and shown to the agent on every future run."""
        c = s.get(case_id)
        d = c.deduction
        res = OutcomeResult(result)
        pattern, sig = f"{d.platform.value}:{d.reason.value}", signature_of(c.evidence)
        s.record_outcome(Outcome(case_id=case_id, result=res, recovered_cents=recovered_cents, reason_pattern=pattern,
                                 signature=sig, claimed_item=d.claimed_item, lesson=lesson or None))
        if res != OutcomeResult.PENDING:
            note = f"{pattern} [{sig or 'no evidence'}] {res.value}, {fmt_cents(recovered_cents)} recovered."
            s.append_lesson(f"{note} {lesson}".strip())
        s.emit(AgentEventType.TODO_UPDATE, {"case_id": case_id, "status": f"outcome:{res.value}"})
        return _j({"ok": True})

    local = locals()
    names = ["load_payout", "triage_cases", "read_memory", "get_case", "read_ticket_image", "check_ticket_vs_claim",
             "check_pickup_timestamps", "check_repeat_claimant", "lint_dispute", "submit_dispute", "send_dispute",
             "recall_similar_cases", "record_outcome"]
    return {n: local[n] for n in names}
