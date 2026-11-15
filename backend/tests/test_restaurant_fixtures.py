"""The Chutney (Montclair) and Tandoori Flames (Parsippany) samples: synthetic, parse cleanly, and exercise every path."""
import json

import pytest

from reclaim.evidence.checks import gather_evidence, load_tickets
from reclaim.ingest.normalize import detect_platform, load_payout
from reclaim.schemas import EvidenceKind, Platform
from reclaim.triage.queue import triage

CASES = [
    ("chutney_montclair_doordash_payout.csv", Platform.DOORDASH, 9, "doordash:DD-51102", "doordash:DD-51152", "doordash:DD-50980", "Momo"),
    ("tandoori_flames_parsippany_ubereats_payout.csv", Platform.UBEREATS, 10, "ubereats:UE-tf01a", "ubereats:UE-tf06f", "ubereats:UE-tf00z", "Biryani"),
]


@pytest.fixture(params=CASES, ids=[c[0].split("_")[0] for c in CASES])
def sample(request, fix, today):
    f, platform, n, weak_id, strong_id, expired_id, food = request.param
    ds = load_payout(fix / f).deductions
    tk = load_tickets(fix / "tickets.json")
    ev = {d.id: gather_evidence(d, ds, tk) for d in ds}
    return dict(file=f, platform=platform, n=n, weak=weak_id, strong=strong_id, expired=expired_id, food=food, ds=ds,
                before=triage(ds, today), after=triage(ds, today, evidence_by_id=ev), ev=ev, fix=fix)


def test_parses_cleanly_on_the_right_platform(sample):
    assert detect_platform(sample["fix"] / sample["file"]) == sample["platform"]
    assert len(sample["ds"]) == sample["n"]
    assert {d.platform for d in sample["ds"]} == {sample["platform"]}


def test_menu_matches_the_restaurant(sample):
    items = " ".join(d.claimed_item or "" for d in sample["ds"])
    assert sample["food"] in items


def test_weak_case_leads_then_is_demoted_after_evidence(sample):
    assert sample["before"][0].id == sample["weak"]
    after = sample["after"]
    assert after[0].id == sample["strong"] and after[0].id != sample["weak"]
    weak = next(c for c in after if c.id == sample["weak"])
    assert weak.weak and weak.confidence <= 35


def test_strong_case_is_ticket_omits_item(sample):
    kinds = {e.kind for e in sample["ev"][sample["strong"]]}
    assert EvidenceKind.TICKET_OMITS_ITEM in kinds


def test_repeat_claimant_and_expired_and_skip(sample):
    assert any(e.kind == EvidenceKind.REPEAT_CLAIMANT for evs in sample["ev"].values() for e in evs)
    exp = next(c for c in sample["after"] if c.id == sample["expired"])
    assert exp.recommend_skip and exp.expected_cents == 0 and exp.confidence == 0
    assert sum(c.recommend_skip for c in sample["after"]) >= 2  # the expired case plus the low-odds "other" claim


def test_tickets_exist_and_are_labelled_synthetic(sample):
    tk = load_tickets(sample["fix"] / "tickets.json")
    for d in sample["ds"]:
        t = tk.get(d.order_id)
        if t:
            assert (sample["fix"].parent / t.image_path).exists()


def test_samples_index_and_disclaimer(fix):
    idx = json.loads((fix / "samples.json").read_text())
    assert all((fix / x["file"]).exists() and "synthetic" in x["note"] for x in idx)
    text = (fix / "SYNTHETIC.md").read_text().lower()
    assert "chutney" in text and "tandoori flames" in text and "not data from either restaurant" in text


def test_api_lists_labelled_samples(fix, tmp_path, today):
    from fastapi.testclient import TestClient
    from reclaim.api.main import Settings, create_app
    c = TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "d", cases=tmp_path / "c", today=today)))
    names = {x["file"]: x for x in c.get("/api/fixtures").json()}
    assert names["chutney_montclair_doordash_payout.csv"]["label"].startswith("Chutney")
    assert names["tandoori_flames_parsippany_ubereats_payout.csv"]["platform"] == "Uber Eats"
