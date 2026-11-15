"""Rule 10: raw customer names stay in the local payout file. Nothing the model sees may contain one."""
import csv
import json

import pytest

from reclaim.agent.session import Session
from reclaim.agent.tools import build_tools

FILES = ["doordash_payout.csv", "chutney_montclair_doordash_payout.csv", "tandoori_flames_parsippany_ubereats_payout.csv"]


def names_in(path):
    out = set()
    for r in csv.DictReader(open(path)):
        for k, v in r.items():
            if "customer" in k.lower() and v and v.strip():
                out.add(v.strip().lower())
    return out


@pytest.mark.parametrize("name", FILES)
def test_no_raw_customer_name_reaches_any_tool_output(tmp_path, fix, today, name):
    names = names_in(fix / name)
    assert names, "fixture should contain customer names for this test to mean anything"
    s = Session(tmp_path / "cases", fix / "tickets.json", today, memory_dir=tmp_path / "memory")
    t = build_tools(s)
    seen = [t["load_payout"].invoke({"path": str(fix / name)}), t["triage_cases"].invoke({})]
    for cid in list(s.cases):
        seen.append(t["get_case"].invoke({"case_id": cid}))
        for n in ("check_ticket_vs_claim", "check_pickup_timestamps", "check_repeat_claimant"):
            seen.append(t[n].invoke({"case_id": cid}))
        seen.append(t["get_case"].invoke({"case_id": cid}))
    blob = " ".join(seen).lower()
    leaked = [n for n in names if n in blob]
    assert not leaked, f"customer names leaked to model-visible output: {leaked}"
    json.loads(seen[0])


def test_case_folders_hold_no_raw_names(tmp_path, fix, today):
    names = names_in(fix / "doordash_payout.csv")
    s = Session(tmp_path / "cases", fix / "tickets.json", today, memory_dir=tmp_path / "memory")
    t = build_tools(s)
    t["load_payout"].invoke({"path": str(fix / "doordash_payout.csv")})
    for cid in list(s.cases):
        t["check_repeat_claimant"].invoke({"case_id": cid})
        s.persist(cid)
    text = " ".join(p.read_text().lower() for p in (tmp_path / "cases").rglob("*") if p.is_file())
    assert not [n for n in names if n in text]
