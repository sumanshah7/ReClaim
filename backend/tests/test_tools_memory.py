import json

import pytest

from reclaim.agent.session import Session
from reclaim.agent.tools import build_tools
from reclaim.schemas import CaseStatus, Outcome, OutcomeResult
from reclaim.triage.memory import Memory, signature_of

DD = "doordash:DD-48230"


@pytest.fixture
def env(tmp_path, fix, today):
    s = Session(tmp_path / "cases", fix / "tickets.json", today, memory_dir=tmp_path / "memory")
    t = build_tools(s)
    t["load_payout"].invoke({"path": str(fix / "doordash_payout.csv")})
    return s, t


def call(t, name, **kw):
    return json.loads(t[name].invoke(kw))


def investigate(t, cid=DD):
    for n in ("check_ticket_vs_claim", "check_pickup_timestamps", "check_repeat_claimant"):
        call(t, n, case_id=cid)


GOOD = ("We are asking for review of order DD-48230 placed on 2026-11-04. The order was ready at 13:24 and "
        "picked up at 13:29 [DD-48230:pickup_handoff]. We would appreciate a review and reversal of the $18.75 deduction.")
IDS = ["DD-48230:pickup_handoff"]   # a ticket listing the item only proves it was ordered, so it is not cited as support


# ---- Rule 1: approval gate ---------------------------------------------------------------
def test_send_without_approval_sends_nothing(env):
    s, t = env
    investigate(t)
    assert call(t, "submit_dispute", case_id=DD, body=GOOD, cited_evidence_ids=IDS)["ok"]
    r = call(t, "send_dispute", case_id=DD)
    assert not r["ok"] and s.get(DD).status == CaseStatus.AWAITING_APPROVAL
    assert not (s.case_dir(DD) / "packet.md").exists()


def test_send_after_approval_writes_packet_and_pending_outcome(env):
    s, t = env
    investigate(t)
    call(t, "submit_dispute", case_id=DD, body=GOOD, cited_evidence_ids=IDS)
    s.approve(DD)
    assert call(t, "send_dispute", case_id=DD)["ok"]
    assert s.get(DD).status == CaseStatus.SENT
    packet = (s.case_dir(DD) / "packet.md").read_text()
    assert "DD-48230:pickup_handoff" in packet and "source:" in packet
    assert s.memory.count() == 1 and s.memory.stats("doordash:missing_item") == (0, 0)  # pending is ignored


def test_cannot_approve_undrafted_case(env):
    s, _ = env
    with pytest.raises(ValueError):
        s.approve(DD)


def test_skip_is_recorded_and_not_sendable(env):
    s, t = env
    investigate(t)
    call(t, "submit_dispute", case_id=DD, body=GOOD, cited_evidence_ids=IDS)
    s.skip(DD)
    assert call(t, "send_dispute", case_id=DD)["ok"] is False
    assert json.loads((s.case_dir(DD) / "decision.json").read_text())["decision"] == "skipped"


# ---- Rules 2 and 4: evidence and wording ---------------------------------------------------
def test_dispute_rejects_unknown_evidence_and_accusations(env):
    s, t = env
    investigate(t)
    r = call(t, "submit_dispute", case_id=DD, body=GOOD, cited_evidence_ids=["DD-48230:invented"])
    assert not r["ok"] and any("unknown evidence id" in e for e in r["errors"])
    bad = GOOD.replace("We would appreciate", "The customer lied, this was fraud. We would appreciate")
    r = call(t, "submit_dispute", case_id=DD, body=bad, cited_evidence_ids=IDS)
    assert not r["ok"] and any("accusatory" in e for e in r["errors"])


def test_dispute_must_name_order_and_cite_supporting_evidence(env):
    _, t = env
    investigate(t)
    r = call(t, "submit_dispute", case_id=DD, body=GOOD.replace("DD-48230", "this order"), cited_evidence_ids=IDS)
    assert any("must reference order" in e for e in r["errors"])
    assert any("cite at least one" in e for e in call(t, "submit_dispute", case_id=DD, body=GOOD, cited_evidence_ids=[])["errors"])


def test_retry_limit_after_one_retry(env):
    _, t = env
    investigate(t)
    for _ in range(2):
        assert not call(t, "submit_dispute", case_id=DD, body="too short", cited_evidence_ids=IDS)["ok"]
    r = call(t, "submit_dispute", case_id=DD, body=GOOD, cited_evidence_ids=IDS)
    assert not r["ok"] and "retry limit" in r["errors"][0]


def test_weak_case_with_no_supporting_evidence_cannot_be_submitted(env):
    _, t = env
    call(t, "check_ticket_vs_claim", case_id="doordash:DD-48211")
    r = call(t, "submit_dispute", case_id="doordash:DD-48211", body=GOOD.replace("DD-48230", "DD-48211"),
             cited_evidence_ids=["DD-48211:ticket_missing"])
    assert not r["ok"] and any("supports" in e for e in r["errors"])


def test_skip_recommended_case_cannot_be_submitted(env):
    _, t = env
    r = call(t, "submit_dispute", case_id="doordash:DD-47990", body=GOOD.replace("DD-48230", "DD-47990"), cited_evidence_ids=[])
    assert not r["ok"] and any("skipping" in e for e in r["errors"])


def test_tools_return_clean_errors_not_crashes(env):
    _, t = env
    assert call(t, "get_case", case_id="doordash:NOPE")["ok"] is False
    assert call(t, "load_payout", path="/does/not/exist.csv")["ok"] is False


# ---- Replan --------------------------------------------------------------------------------
def test_replan_event_for_weak_top_case(env):
    s, t = env
    investigate(t, "doordash:DD-48211")
    ev = [e for e in s.events if e.type.value == "replan"]
    assert ev and ev[0].payload["case_id"] == "doordash:DD-48211" and ev[0].payload["to_rank"] > 1


def test_trace_written_per_case(env):
    s, t = env
    investigate(t)
    lines = (s.case_dir(DD) / "trace.jsonl").read_text().splitlines()
    assert len(lines) >= 3 and "check_ticket_vs_claim" in lines[0]


# ---- Persistent memory: improves with similar cases ------------------------------------------
def _outcome(m, i, result, sig, pattern="doordash:missing_item", lesson=None):
    m.record(Outcome(case_id=f"h{i}", result=result, reason_pattern=pattern, signature=sig, lesson=lesson))


def test_signature_stats_override_broad_only_with_enough_samples():
    m = Memory()
    _outcome(m, 1, OutcomeResult.LOST, "a")
    for i in range(2, 5):
        _outcome(m, i, OutcomeResult.WON, "b")
    assert m.best_stats("doordash:missing_item", "a")[1] == "same claim type"      # 1 sample: back off
    assert m.best_stats("doordash:missing_item", "b") == ((3, 3), "similar evidence pattern")


def test_similar_past_wins_raise_and_losses_lower_probability(env, today):
    from reclaim.triage.scoring import score_case
    s, t = env
    investigate(t)
    c = s.get(DD)
    base = score_case(c.deduction, c.evidence, today).p_win_bp
    won = score_case(c.deduction, c.evidence, today, (3, 3), "similar evidence pattern")
    lost = score_case(c.deduction, c.evidence, today, (0, 3), "similar evidence pattern")
    assert lost.p_win_bp < base < won.p_win_bp
    assert any(r.text.startswith("Memory: 3 of 3") for r in won.reasons)


def test_memory_changes_next_run_via_session(tmp_path, fix, today):
    """End to end: outcomes recorded in one run change scoring in the next, from the same sqlite file."""
    db = tmp_path / "reclaim.db"
    s1 = Session(tmp_path / "r1", fix / "tickets.json", today, memory=Memory(db))
    t1 = build_tools(s1)
    t1["load_payout"].invoke({"path": str(fix / "doordash_payout.csv")})
    investigate(t1)
    sig = signature_of(s1.get(DD).evidence)
    before = s1.get(DD).p_win_bp
    for i in range(3):
        _outcome(s1.memory, i, OutcomeResult.LOST, sig)
    s2 = Session(tmp_path / "r2", fix / "tickets.json", today, memory=Memory(db))  # new run, same db
    t2 = build_tools(s2)
    t2["load_payout"].invoke({"path": str(fix / "doordash_payout.csv")})
    investigate(t2)
    assert s2.get(DD).p_win_bp < before
    assert any(r.text.startswith("Memory: 0 of 3") for r in s2.get(DD).reasons)


def test_recall_similar_cases_and_lessons_file(env):
    s, t = env
    investigate(t)
    r = call(t, "record_outcome", case_id=DD, result="won", recovered_cents=1875,
             lesson="Ticket plus quick handoff was enough.")
    assert r["ok"]
    assert "Ticket plus quick handoff" in s.lessons_path.read_text()
    rec = call(t, "recall_similar_cases", case_id=DD)
    assert rec["resolved_similar"] == 1 and rec["cases"][0]["lesson"].startswith("Ticket plus")
    assert rec["cases"][0]["same_evidence_pattern"] is True


def test_pending_outcome_writes_no_lesson(env):
    s, t = env
    investigate(t)
    call(t, "record_outcome", case_id=DD, result="pending")
    assert not s.lessons_path.exists()


# ---- Concurrency: the real model runs the three checks in parallel on separate threads -------------------------------
def test_parallel_checks_lose_no_evidence_and_are_order_independent(tmp_path, fix, today):
    import itertools
    from concurrent.futures import ThreadPoolExecutor
    checks = ("check_ticket_vs_claim", "check_pickup_timestamps", "check_repeat_claimant")
    seen_outputs, seen_final = set(), set()
    for n, order in enumerate(itertools.permutations(checks)):
        for rep in range(8):
            s = Session(tmp_path / f"c{n}{rep}", fix / "tickets.json", today, memory_dir=tmp_path / f"m{n}{rep}")
            t = build_tools(s)
            t["load_payout"].invoke({"path": str(fix / "doordash_payout.csv")})
            cid = "doordash:DD-48244"  # a repeat claimant: all three checks produce evidence
            with ThreadPoolExecutor(max_workers=3) as ex:
                outs = list(ex.map(lambda name: t[name].invoke({"case_id": cid}), order))
            by_check = dict(zip(order, outs))
            seen_outputs.add(tuple(by_check[c] for c in checks))      # outputs, in a fixed check order
            c = s.get(cid)
            assert len(c.evidence) == 3, "a parallel update was lost"
            seen_final.add((c.p_win_bp, c.confidence, tuple(sorted(e.id for e in c.evidence))))
    assert len(seen_outputs) == 1, "tool outputs depend on thread timing, which breaks the replay cache"
    assert len(seen_final) == 1


def test_check_results_carry_no_state_dependent_fields(env):
    s, t = env
    for name in ("check_ticket_vs_claim", "check_pickup_timestamps", "check_repeat_claimant"):
        r = call(t, name, case_id="doordash:DD-48244")
        assert not ({"win_probability_pct", "weak", "rank_before", "rank_after"} & set(r)), name


def test_memory_view_explains_the_probability_shift(env):
    from reclaim.api.main import _memory_view
    s, t = env
    assert _memory_view(s, s.get(DD)) is None                       # no history: nothing to explain
    for i, res in enumerate(["won", "won", "lost"]):
        s.record_outcome(Outcome(case_id=f"x{i}", result=OutcomeResult(res), reason_pattern="doordash:missing_item",
                                 signature="", claimed_item="Green Smoothie", lesson=f"lesson {i}"))
    s.append_lesson("doordash:missing_item [] won, $1.00 recovered. Tickets matter.")
    m = _memory_view(s, s.get(DD))
    assert (m["won"], m["total"], m["claim"]) == (2, 3, "missing item")
    assert m["adjusted_pct"] > m["base_pct"] == 55                   # 2 of 3 won pulls the 55% base upward
    assert any("Tickets matter" in l for l in m["lessons"]) and len(m["similar"]) == 3
