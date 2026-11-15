"""Areas 2-4: triage, evidence and dispute-writer edge cases."""
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reclaim.agent.session import Session
from reclaim.api.main import Settings, create_app
from reclaim.dispute.packet import write_packet
from reclaim.evidence import checks
from reclaim.evidence.checks import load_tickets
from reclaim.schemas import ClaimReason, Evidence, EvidenceKind, Ticket
from reclaim.triage.queue import hero_stats, triage
from reclaim.triage.scoring import BASE_BP, score_case
from tests.edge_helpers import dd_csv, dd_row, ded, write
from tests.policy_model import PolicyChatModel

TODAY = date(2026, 11, 14)
TICKETS = Path(__file__).resolve().parents[2] / "fixtures" / "tickets.json"


def ticket(items, conf=1.0, ready=datetime(2026, 11, 4, 13, 24), image="fixtures/tickets/x.png"):
    return Ticket(order_id="DD-1", items=items, ready_ts=ready, image_path=image, extraction_confidence=conf)


# ================= Area 2: scoring and triage =================================================================
def test_zero_cases_means_an_empty_queue_and_an_empty_hero():
    assert triage([], TODAY) == []
    h = hero_stats([])
    assert (h.recoverable_cents, h.workable_cases, h.next_deadline, h.next_deadline_days) == (0, 0, None, None)


def test_all_cases_tied_sort_deterministically_by_deadline_then_id():
    deds = [ded(f"DD-{n}") for n in (5, 3, 9, 1, 7)]
    expected = [c.id for c in triage(deds, TODAY)]
    assert expected == sorted(expected)
    for _ in range(5):
        random.shuffle(deds)
        assert [c.id for c in triage(deds, TODAY)] == expected


def test_tie_on_score_is_broken_by_earlier_deadline():
    early, late = ded("DD-9", payout=date(2026, 11, 8)), ded("DD-1", payout=date(2026, 11, 12))
    assert [c.id for c in triage([late, early], TODAY)] == ["doordash:DD-9", "doordash:DD-1"]


def test_a_passed_deadline_is_zeroed_skipped_and_sinks():
    gone, live = ded("DD-1", payout=date(2026, 10, 1)), ded("DD-2")
    cases = triage([gone, live], TODAY)
    expired = next(c for c in cases if c.id.endswith("DD-1"))
    assert expired.recommend_skip and "passed" in expired.skip_reason
    assert expired.expected_cents == 0 and expired.recoverable_cents == 0 and expired.confidence == 0
    assert cases[-1].id == expired.id
    assert hero_stats(cases).workable_cases == 1


def test_a_deadline_today_is_still_workable():
    c = triage([ded(payout=TODAY - timedelta(days=14))], TODAY)[0]      # DoorDash window is 14 days
    assert c.days_left == 0 and not c.recommend_skip and c.recoverable_cents == 2000


def test_a_deadline_yesterday_is_expired():
    c = triage([ded(payout=TODAY - timedelta(days=15))], TODAY)[0]
    assert c.days_left == -1 and c.recommend_skip


def test_no_history_means_the_plain_base_rate_and_no_memory_line():
    c = triage([ded()], TODAY, history_fn=lambda p: ((0, 0), "same claim type"))[0]
    assert c.p_win_bp == BASE_BP[ClaimReason.MISSING_ITEM]
    assert not any("Memory" in r.text for r in c.reasons)


# ================= Area 3: evidence ===========================================================================
def test_no_ticket_is_recorded_as_a_missing_artifact_and_marks_the_case_weak():
    ev = checks.check_ticket_vs_claim(ded(order="DD-1"), None)
    assert ev.kind == EvidenceKind.MISSING_ARTIFACT and ev.supports == 0 and ev.source_ref
    assert score_case(ded(order="DD-1"), [ev], TODAY, (0, 0), "x").weak


def test_an_illegible_ticket_is_missing_evidence_not_a_guess():
    ev = checks.check_ticket_vs_claim(ded(), ticket(["Green Smoothie"], conf=0.3))
    assert ev.kind == EvidenceKind.MISSING_ARTIFACT and "could not be read" in ev.summary


def test_a_refund_that_names_no_item_cannot_be_compared():
    ev = checks.check_ticket_vs_claim(ded(item=None), ticket(["Green Smoothie"]))
    assert ev.kind == EvidenceKind.MISSING_ARTIFACT


def test_unreadable_ticket_data_degrades_one_order_not_the_whole_run(tmp_path):
    p = tmp_path / "tickets.json"
    p.write_text(json.dumps([{"order_id": "DD-1", "items": ["A"], "extraction_confidence": 1.0},
                             {"order_id": "DD-2"},                                   # missing items
                             {"order_id": "DD-3", "items": ["B"], "extraction_confidence": 7}]))   # out of range
    assert set(load_tickets(p)) == {"DD-1"}


def test_a_corrupt_tickets_file_is_a_clear_error(tmp_path):
    p = tmp_path / "tickets.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="tickets"):
        load_tickets(p)


@pytest.fixture
def broken_fixtures(tmp_path):
    fx = tmp_path / "fx"
    (fx / "tickets").mkdir(parents=True)
    (fx / "t_payout.csv").write_text(dd_csv(dd_row("DD-1")))
    (fx / "tickets.json").write_text(json.dumps([{"order_id": "DD-1", "items": ["Green Smoothie"],
                                                  "image_path": "fixtures/tickets/DD-1.png"}]))
    (fx / "tickets" / "DD-1.png").write_bytes(b"this is not a png at all")
    (fx / "tickets" / "DD-2.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return fx


def _client(tmp_path, fx):
    return TestClient(create_app(Settings(fixtures=fx, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY,
                                          model_factory=lambda: PolicyChatModel())))


def test_a_corrupted_image_file_is_not_served_as_an_image(tmp_path, broken_fixtures):
    c = _client(tmp_path, broken_fixtures)
    assert c.get("/api/tickets/DD-1.png").status_code == 404           # bytes are not a PNG/JPEG
    assert c.get("/api/tickets/DD-2.png").status_code == 200           # real signature is served
    assert c.get("/api/tickets/nope.png").status_code == 404


def test_a_corrupt_tickets_file_fails_the_run_start_with_a_readable_message(tmp_path, broken_fixtures):
    (broken_fixtures / "tickets.json").write_text("{not json")
    r = _client(tmp_path, broken_fixtures).post("/api/runs", json={"fixture": "t_payout.csv"})
    assert r.status_code == 503 and "ticket" in r.json()["detail"].lower()


def _p(d, ev):
    return score_case(d, ev, TODAY, (0, 0), "x").p_win_bp


def test_missing_item_claim_ticket_lists_item_is_neutral():
    """A ticket only proves the item was ordered, not that it was packed, so it must not raise a missing-item score."""
    d = ded(reason=ClaimReason.MISSING_ITEM)
    listed = checks.check_ticket_vs_claim(d, ticket(["Green Smoothie"]))
    assert listed.kind == EvidenceKind.TICKET_LISTS_ITEM and listed.supports == 1
    assert _p(d, [listed]) == _p(d, [])
    case = score_case(d, [listed], TODAY, (0, 0), "x")
    assert any("ordered but not that it was packed" in r.text and r.delta == 0 for r in case.reasons)


def test_missing_item_claim_ticket_omits_item_still_adds_thirty_points():
    d = ded(reason=ClaimReason.MISSING_ITEM, item="Chicken Thukpa")
    omitted = checks.check_ticket_vs_claim(d, ticket(["Green Smoothie"]))
    assert omitted.kind == EvidenceKind.TICKET_OMITS_ITEM
    assert _p(d, [omitted]) - _p(d, []) == 3000


def test_wrong_item_claim_ticket_lists_item_still_adds_ten_points():
    d = ded(reason=ClaimReason.WRONG_ITEM)
    listed = checks.check_ticket_vs_claim(d, ticket(["Green Smoothie"]))
    assert _p(d, [listed]) - _p(d, []) == 1000


def test_neutral_ticket_does_not_hide_other_evidence_on_a_missing_item_claim():
    d = ded(reason=ClaimReason.MISSING_ITEM)
    listed = checks.check_ticket_vs_claim(d, ticket(["Green Smoothie"]))
    handoff = checks.check_pickup_timestamps(d, ticket(["Green Smoothie"]))
    assert _p(d, [listed, handoff]) - _p(d, []) == 1000      # only the handoff evidence moves the score


def test_a_partial_item_match_is_neutral_not_a_confident_omission():
    d = ded(item="Chicken Momo (Steamed)")
    ev = checks.check_ticket_vs_claim(d, ticket(["Chicken Momo", "Samosa Chaat"]))
    assert ev.supports == 0 and "similar" in ev.summary
    base = score_case(d, [], TODAY, (0, 0), "x").p_win_bp
    assert score_case(d, [ev], TODAY, (0, 0), "x").p_win_bp == base


def test_non_latin_item_names_do_not_all_match_each_other():
    omit = checks.check_ticket_vs_claim(ded(item="मोमो"), ticket(["चाउमिन"]))
    assert omit.kind == EvidenceKind.TICKET_OMITS_ITEM
    assert checks.check_ticket_vs_claim(ded(item="मोमो"), ticket(["मोमो"])).kind == EvidenceKind.TICKET_LISTS_ITEM


def test_an_item_name_with_no_letters_is_unspecified_not_matched():
    ev = checks.check_ticket_vs_claim(ded(item="🍜"), ticket(["🥟"]))
    assert ev.kind == EvidenceKind.MISSING_ARTIFACT


def test_accents_and_punctuation_do_not_cause_false_omissions():
    assert checks.check_ticket_vs_claim(ded(item="Crème Brûlée"), ticket(["Creme Brulee"])).kind == EvidenceKind.TICKET_LISTS_ITEM
    assert checks.check_ticket_vs_claim(ded(item="momo (steamed)"), ticket(["Momo  Steamed"])).kind == EvidenceKind.TICKET_LISTS_ITEM


# ================= Area 4: dispute writer =====================================================================
def session_with(tmp_path, d, ev):
    s = Session(tmp_path / "cases", TICKETS, TODAY, memory_dir=tmp_path / "mem")
    s.ingest([d])
    for e in ev:
        s.add_evidence(d.id, e)
    return s


def omit_ev(d):
    return Evidence(id=f"{d.order_id}:ticket_omits_item", kind=EvidenceKind.TICKET_OMITS_ITEM,
                    summary=f"The ticket does not list '{d.claimed_item}'.", source_ref="fixtures/tickets/x.png", supports=1)


def body_for(d, extra=""):
    return (f"We are asking for a review of order {d.order_id}. The ticket does not list the item {extra}"
            f"[{d.order_id}:ticket_omits_item]. We would appreciate a review of the deduction.")


@pytest.mark.parametrize("name", ["Cheat Day Burger", "Fake Bacon Bits", "Steak & Eggs", "Abuse-Free Chili"])
def test_an_ordinary_product_name_that_contains_a_banned_word_does_not_block_the_dispute(tmp_path, name):
    d = ded(item=name)
    s = session_with(tmp_path, d, [omit_ev(d)])
    assert s.save_draft(d.id, body_for(d, f"'{name}' "), [f"{d.order_id}:ticket_omits_item"]) == []


def test_accusations_are_still_caught_next_to_an_innocent_product_name(tmp_path):
    d = ded(item="Fake Bacon Bits")
    s = session_with(tmp_path, d, [omit_ev(d)])
    errs = s.save_draft(d.id, body_for(d, "'Fake Bacon Bits' ") + " The customer is lying.", [f"{d.order_id}:ticket_omits_item"])
    assert any("lying" in e for e in errs)


@pytest.mark.parametrize("name", ['Crème Brûlée "Deluxe" <b>&amp;</b> 🍜', "मोमो (भाप)", "X" * 3000, "Line\nbreak, comma; tab\t"])
def test_special_and_very_long_product_names_flow_through_draft_and_packet(tmp_path, name):
    d = ded(item=name)
    s = session_with(tmp_path, d, [omit_ev(d)])
    assert s.save_draft(d.id, body_for(d, f"'{name}' "), [f"{d.order_id}:ticket_omits_item"]) == []
    out = tmp_path / "packet"
    out.mkdir()
    write_packet(out, s.get(d.id), s.disputes[d.id], datetime(2026, 11, 14, 12, 0))
    assert name in (out / "packet.md").read_text()


def test_conflicting_evidence_cannot_be_cited_as_support(tmp_path):
    d = ded(item="Chicken Momo (Steamed)")
    partial = checks.check_ticket_vs_claim(d, ticket(["Chicken Momo"]))
    early = checks.check_pickup_timestamps(d.model_copy(update={"pickup_ts": datetime(2026, 11, 4, 13, 0)}),
                                           ticket(["Chicken Momo"]))
    assert early.supports == -1
    s = session_with(tmp_path, d, [partial, early])
    errs = s.save_draft(d.id, f"We are asking for a review of order {d.order_id}. {partial.summary} [{partial.id}] "
                              f"We would appreciate a review.", [partial.id, early.id])
    assert any("supports" in e for e in errs) and d.id not in s.disputes


def test_a_draft_must_name_the_order(tmp_path):
    d = ded()
    s = session_with(tmp_path, d, [omit_ev(d)])
    errs = s.save_draft(d.id, "We would like this deduction reviewed, thank you very much for your time.",
                        [f"{d.order_id}:ticket_omits_item"])
    assert any("reference order" in e for e in errs)
