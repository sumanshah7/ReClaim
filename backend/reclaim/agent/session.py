"""Shared run state: cases, approvals, events and per-case folders (rules 1, 8)."""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from ..dispute.lint import lint_dispute
from ..evidence.checks import load_tickets
from ..schemas import (AgentEvent, AgentEventType, Case, CaseStatus, Deduction, Dispute, Evidence, Outcome)
from ..triage.memory import Memory, signature_of
from ..triage.queue import hero_stats, sort_cases, triage
from ..triage.scoring import score_case

MAX_DRAFT_FAILURES = 2  # one retry after the first failure (every LLM output is validated, retried once)


LESSONS_HEADER = (
    "# Reclaim memory: lessons from past disputes\n\n"
    "Each line is a takeaway from a resolved case. Use them when weighing similar cases. "
    "They are history, not guarantees.\n\n"
)


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and rename, so a crash mid-write leaves the old file intact, never a half-written one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def safe_id(case_id: str) -> str:
    return case_id.replace(":", "_").replace("/", "_")


class Session:
    def __init__(self, cases_dir: Path, tickets_path: Path, today: date, memory: Memory | None = None,
                 clock: Callable[[], datetime] = datetime.now, memory_dir: Path | None = None):
        self.memory_dir = Path(memory_dir) if memory_dir else Path(cases_dir).parent / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.cases_dir = Path(cases_dir)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.tickets = load_tickets(tickets_path)
        self.today = today
        self.memory = memory or Memory()
        self.clock = clock
        self.deductions: list[Deduction] = []
        self.cases: dict[str, Case] = {}
        self.disputes: dict[str, Dispute] = {}
        self.approved: set[str] = set()
        self.draft_failures: dict[str, int] = {}
        self.events: list[AgentEvent] = []
        self._lock = threading.Lock()
        self._case_lock = threading.RLock()  # serialises evidence updates from parallel tool calls

    # ---- events -------------------------------------------------------------------------
    def emit(self, type_: AgentEventType, payload: dict) -> AgentEvent:
        ev = AgentEvent(ts=self.clock(), type=type_, payload=payload)
        with self._lock:
            self.events.append(ev)
        return ev

    def events_since(self, i: int) -> list[AgentEvent]:
        with self._lock:
            return self.events[i:]

    # ---- cases --------------------------------------------------------------------------
    def case_dir(self, case_id: str) -> Path:
        d = self.cases_dir / safe_id(case_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def history(self, pattern: str, signature: str = "") -> tuple[tuple[int, int], str]:
        return self.memory.best_stats(pattern, signature)

    @property
    def lessons_path(self) -> Path:
        return self.memory_dir / "AGENTS.md"

    def append_lesson(self, line: str) -> None:
        """Persist a one-line lesson to the agent's AGENTS.md memory, loaded into its prompt on every run."""
        if not self.lessons_path.exists():
            self.lessons_path.write_text(LESSONS_HEADER)
        with open(self.lessons_path, "a") as fh:
            fh.write(f"- {line.strip()}\n")

    def ingest(self, deductions: list[Deduction]) -> list[Case]:
        known = {d.id for d in self.deductions}
        for d in deductions:           # one deduction per case id, even inside a single batch
            if d.id not in known:
                known.add(d.id)
                self.deductions.append(d)
        for c in triage(self.deductions, self.today, history_fn=lambda p: self.history(p)):
            old = self.cases.get(c.id)
            self.cases[c.id] = c if old is None else old
        return self.ranked()

    def ranked(self) -> list[Case]:
        return sort_cases(list(self.cases.values()))

    def rank_of(self, case_id: str) -> int:
        return [c.id for c in self.ranked()].index(case_id) + 1

    def hero(self):
        return hero_stats(self.ranked())

    def get(self, case_id: str) -> Case:
        if case_id not in self.cases:
            raise KeyError(f"unknown case id: {case_id}")
        return self.cases[case_id]

    def add_evidence(self, case_id: str, ev: Evidence) -> dict:
        """Attach evidence, rescore deterministically, and report any queue change."""
        with self._case_lock:
            return self._add_evidence(case_id, ev)

    def _add_evidence(self, case_id: str, ev: Evidence) -> dict:
        old = self.get(case_id)
        before = [c.id for c in self.ranked()]
        evidence = [e for e in old.evidence if e.id != ev.id] + [ev]
        d = old.deduction
        stats, scope = self.history(f"{d.platform.value}:{d.reason.value}", signature_of(evidence))
        new = score_case(d, evidence, self.today, stats, scope)
        self.cases[case_id] = new.model_copy(update={"status": CaseStatus.INVESTIGATING})
        after = [c.id for c in self.ranked()]
        self.persist(case_id)
        change = {"rank_before": before.index(case_id) + 1, "rank_after": after.index(case_id) + 1}
        if new.weak and change["rank_after"] > change["rank_before"]:
            promoted = after[change["rank_before"] - 1]
            self.emit(AgentEventType.REPLAN, {
                "case_id": case_id, "from_rank": change["rank_before"], "to_rank": change["rank_after"],
                "promoted_case_id": promoted,
                "reason": f"{ev.summary} Win probability fell to {new.p_win_bp // 100}%.",
            })
        return change

    def persist(self, case_id: str) -> None:
        c = self.get(case_id)
        d = self.case_dir(case_id)
        atomic_write(d / "case.json", c.model_dump_json(indent=2))
        atomic_write(d / "evidence.json", json.dumps([e.model_dump(mode="json") for e in c.evidence], indent=2))

    def trace(self, case_id: str, record: dict) -> None:
        with open(self.case_dir(case_id) / "trace.jsonl", "a") as fh:
            fh.write(json.dumps({"ts": self.clock().isoformat(), **record}, default=str) + "\n")

    # ---- drafting and approval (rules 1, 2, 4) -------------------------------------------
    def validate_draft(self, case_id: str, body: str, cited: list[str]) -> list[str]:
        c = self.get(case_id)
        t = self.tickets.get(c.deduction.order_id)
        errors = lint_dispute(body, ignore=[c.deduction.claimed_item or "", *(t.items if t else [])])
        ids = {e.id for e in c.evidence}
        supports = {e.id for e in c.evidence if e.supports >= 1}
        if c.recommend_skip:
            errors.append(f"case is recommended for skipping: {c.skip_reason}")
        if not cited:
            errors.append("cite at least one evidence id")
        errors += [f"unknown evidence id: {i}" for i in cited if i not in ids]
        if cited and not (set(cited) & supports):
            errors.append("none of the cited evidence supports the restaurant's position")
        errors += [f"evidence {i} does not support the restaurant's position (it is neutral or against), so it cannot "
                   "be cited as support; cite only supporting evidence" for i in cited if i in ids and i not in supports]
        if c.deduction.order_id not in body:
            errors.append(f"dispute text must reference order {c.deduction.order_id}")
        return errors

    def save_draft(self, case_id: str, body: str, cited: list[str]) -> list[str]:
        errors = self.validate_draft(case_id, body, cited)
        if errors:
            self.draft_failures[case_id] = self.draft_failures.get(case_id, 0) + 1
            return errors
        self.disputes[case_id] = Dispute(case_id=case_id, body=body, cited_evidence_ids=cited, lint_passed=True)
        atomic_write(self.case_dir(case_id) / "draft.md", body)
        self.cases[case_id] = self.get(case_id).model_copy(update={"status": CaseStatus.AWAITING_APPROVAL})
        self.persist(case_id)
        self.emit(AgentEventType.TODO_UPDATE, {"case_id": case_id, "status": "drafted"})
        return []

    def approve(self, case_id: str) -> None:
        """Called only by the human-facing layer (API / Photon) before the graph is resumed."""
        c = self.get(case_id)
        if c.status != CaseStatus.AWAITING_APPROVAL or case_id not in self.disputes:
            raise ValueError("only a drafted case awaiting approval can be approved")
        self.approved.add(case_id)
        self._decision(case_id, "approved")

    def skip(self, case_id: str) -> None:
        self.cases[case_id] = self.get(case_id).model_copy(update={"status": CaseStatus.SKIPPED})
        self._decision(case_id, "skipped")
        self.persist(case_id)

    def _decision(self, case_id: str, what: str) -> None:
        atomic_write(self.case_dir(case_id) / "decision.json",
                     json.dumps({"case_id": case_id, "decision": what, "at": self.clock().isoformat()}, indent=2))

    def record_outcome(self, o: Outcome) -> None:
        self.memory.record(o)
