from reclaim.evidence.checks import (check_pickup_timestamps, check_repeat_claimant, check_ticket_vs_claim,
                                     gather_evidence, load_tickets)
from reclaim.ingest.normalize import load_payout
from reclaim.schemas import EvidenceKind, Outcome, OutcomeResult
from reclaim.triage.memory import Memory
from reclaim.triage.queue import hero_stats, sort_cases, triage
from reclaim.triage.scoring import blended_base, score_case


def _ds(fix):
    return load_payout(fix / "doordash_payout.csv").deductions


def _evidence(fix):
    ds, tk = _ds(fix), load_tickets(fix / "tickets.json")
    return ds, {d.id: gather_evidence(d, ds, tk) for d in ds}


def test_ticket_check_variants(fix):
    ds, tk = _ds(fix), load_tickets(fix / "tickets.json")
    by = {d.order_id: d for d in ds}
    assert check_ticket_vs_claim(by["DD-48211"], tk.get("DD-48211")).kind == EvidenceKind.MISSING_ARTIFACT
    assert check_ticket_vs_claim(by["DD-48230"], tk["DD-48230"]).kind == EvidenceKind.TICKET_LISTS_ITEM
    assert check_ticket_vs_claim(by["DD-48290"], tk["DD-48290"]).kind == EvidenceKind.TICKET_OMITS_ITEM
    assert check_ticket_vs_claim(by["DD-48301"], tk["DD-48301"]).kind == EvidenceKind.MISSING_ARTIFACT  # no item named


def test_every_evidence_has_source_ref(fix):
    _, ev = _evidence(fix)
    assert all(e.source_ref for evs in ev.values() for e in evs)


def test_pickup_check(fix):
    ds, tk = _ds(fix), load_tickets(fix / "tickets.json")
    d = next(x for x in ds if x.order_id == "DD-48230")
    e = check_pickup_timestamps(d, tk["DD-48230"])
    assert e.supports == 1 and "5 min" in e.summary
    assert check_pickup_timestamps(next(x for x in ds if x.order_id == "DD-48211"), None) is None


def test_repeat_claimant_requires_three(fix):
    ds = _ds(fix)
    jordan = next(x for x in ds if x.order_id == "DD-48244")
    e = check_repeat_claimant(jordan, ds)
    assert e and "3 refund claims" in e.summary
    assert check_repeat_claimant(next(x for x in ds if x.order_id == "DD-48230"), ds) is None
    for w in ("lied", "fraud", "false", "scam"):  # rule 4: factual wording only
        assert w not in e.summary.lower()


def test_weak_top_case_is_demoted_after_evidence(fix, today):
    ds, ev = _evidence(fix)
    before = triage(ds, today)
    assert before[0].id == "doordash:DD-48211"  # biggest value leads on base rates alone
    after = triage(ds, today, evidence_by_id=ev)
    top = after[0]
    assert top.id != "doordash:DD-48211"
    weak = next(c for c in after if c.id == "doordash:DD-48211")
    assert weak.weak and weak.confidence <= 35 and any("missing" in r.text.lower() for r in weak.reasons)


def test_expired_case_is_skipped(fix, today):
    ds, ev = _evidence(fix)
    c = next(c for c in triage(ds, today, evidence_by_id=ev) if c.id == "doordash:DD-47990")
    assert c.recommend_skip and c.recoverable_cents == 0 and c.expected_cents == 0 and c.days_left < 0


def test_other_reason_recommended_skip(fix, today):
    ds, ev = _evidence(fix)
    c = next(c for c in triage(ds, today, evidence_by_id=ev) if c.id == "doordash:DD-48301")
    assert c.recommend_skip and c.skip_reason


def test_every_case_has_reasons(fix, today):
    ds, ev = _evidence(fix)
    assert all(c.reasons for c in triage(ds, today, evidence_by_id=ev))


def test_sort_value_then_deadline_tiebreak(fix, today):
    ds = _ds(fix)
    a = score_case(ds[0], [], today); b = score_case(ds[0].model_copy(update={"id": "z"}), [], today)
    b = b.model_copy(update={"deadline": a.deadline.replace(day=a.deadline.day - 1)})
    assert a.expected_cents == b.expected_cents
    assert sort_cases([a, b])[0].id == "z"  # earlier deadline wins the tie


def test_skips_sink_below_workable(fix, today):
    ds, ev = _evidence(fix)
    cases = triage(ds, today, evidence_by_id=ev)
    flags = [c.recommend_skip for c in cases]
    assert flags == sorted(flags)


def test_hero_stats(fix, today):
    ds, ev = _evidence(fix)
    cases = triage(ds, today, evidence_by_id=ev)
    h = hero_stats(cases)
    assert h.recoverable_cents == sum(c.expected_cents for c in cases if not c.recommend_skip)
    assert h.next_deadline == min(c.deadline for c in cases if not c.recommend_skip)
    assert hero_stats([]).next_deadline is None


def test_probability_bounds(fix, today):
    ds, ev = _evidence(fix)
    assert all(500 <= c.p_win_bp <= 9000 for c in triage(ds, today, evidence_by_id=ev))


def test_memory_shifts_probability(fix, today):
    m = Memory()
    for i in range(3):
        m.record(Outcome(case_id=f"x{i}", result=OutcomeResult.LOST, reason_pattern="doordash:missing_item"))
    m.record(Outcome(case_id="p", result=OutcomeResult.PENDING, reason_pattern="doordash:missing_item"))
    assert m.stats("doordash:missing_item") == (0, 3)  # pending ignored
    assert blended_base(5500, 0, 3) < 5500
    d = next(x for x in _ds(fix) if x.order_id == "DD-48230")
    assert triage([d], today, history_fn=m.stats)[0].p_win_bp < triage([d], today)[0].p_win_bp
    assert blended_base(5500, 0, 0) == 5500
    assert any("Prior outcomes" in r.text for r in triage([d], today, history_fn=m.stats)[0].reasons)


def test_memory_upsert():
    m = Memory()
    m.record(Outcome(case_id="a", result=OutcomeResult.PENDING, reason_pattern="p"))
    m.record(Outcome(case_id="a", result=OutcomeResult.WON, reason_pattern="p", recovered_cents=100))
    assert m.stats("p") == (1, 1)
