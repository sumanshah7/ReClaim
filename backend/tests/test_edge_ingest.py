"""Area 1: CSV parsing edge cases."""
import time
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reclaim.agent.session import Session
from reclaim.api.main import Settings, create_app
from reclaim.ingest.normalize import load_payout
from reclaim.schemas import ClaimReason
from reclaim.triage.queue import triage
from tests.edge_helpers import DD_HEADER, dd_csv, dd_row, write
from tests.policy_model import PolicyChatModel

TODAY = date(2026, 11, 14)
TICKETS = Path(__file__).resolve().parents[2] / "fixtures" / "tickets.json"


def test_empty_file_is_rejected_with_a_clear_message(tmp_path):
    with pytest.raises(ValueError, match="could not recognise"):
        load_payout(write(tmp_path, ""))


def test_headers_only_parses_to_nothing_without_errors(tmp_path):
    res = load_payout(write(tmp_path, dd_csv()))
    assert res.deductions == [] and res.errors == []


def test_missing_required_column_names_the_column(tmp_path):
    header = DD_HEADER.replace("Description", "Notes")
    with pytest.raises(ValueError, match="Description"):
        load_payout(write(tmp_path, dd_csv(dd_row(), header=header)))


def test_non_numeric_amount_is_a_row_error_and_other_rows_survive(tmp_path):
    res = load_payout(write(tmp_path, dd_csv(dd_row("DD-1"), dd_row("DD-2", amount="twelve"), dd_row("DD-3"))))
    assert [d.order_id for d in res.deductions] == ["DD-1", "DD-3"]
    assert len(res.errors) == 1 and "row 3" in res.errors[0]


def test_exact_duplicate_rows_are_ignored_and_reported(tmp_path):
    res = load_payout(write(tmp_path, dd_csv(dd_row("DD-1"), dd_row("DD-1"))))
    assert len(res.deductions) == 1 and "duplicate" in res.errors[0]


def test_two_different_refunds_on_one_order_never_become_two_orphaned_deductions(tmp_path):
    """Case ids are platform:order_id, so a second refund for the same order must be reported, not silently dropped
    later (and must not linger in the deductions list that repeat-claimant checks count)."""
    res = load_payout(write(tmp_path, dd_csv(dd_row("DD-1", amount="-5.00"), dd_row("DD-1", amount="-9.00",
                                                                                    reason="Wrong item refund"))))
    assert len(res.deductions) == 1
    assert any("DD-1" in e for e in res.errors)
    s = Session(tmp_path / "cases", TICKETS, TODAY,
                memory_dir=tmp_path / "mem")
    s.ingest(res.deductions + res.deductions)           # even a double ingest keeps one deduction per case
    assert len(s.deductions) == len(s.cases) == 1


def test_unknown_platform_format_is_refused_clearly(tmp_path):
    grubhub = "Grubhub Order #,Date,Issue,Refund Amount\n123,2026-11-04,Item not received,-$12.00\n"
    with pytest.raises(ValueError, match="could not recognise payout format"):
        load_payout(write(tmp_path, grubhub))


def test_unrecognised_reason_wording_is_other_and_recommended_for_skip(tmp_path):
    res = load_payout(write(tmp_path, dd_csv(dd_row("DD-1", reason="Customer reported item not received"))))
    assert res.deductions[0].reason == ClaimReason.OTHER
    case = triage(res.deductions, TODAY)[0]
    assert case.recommend_skip          # conservative: low base rate, never silently dropped and never over-promised


def test_bom_crlf_and_quoted_commas_in_item_names(tmp_path):
    text = "﻿" + dd_csv(dd_row("DD-1", item='"Momo, Steamed (Chicken)"'), eol="\r\n")
    res = load_payout(write(tmp_path, text))
    assert res.deductions[0].claimed_item == "Momo, Steamed (Chicken)" and not res.errors


@pytest.mark.parametrize("raw,deducted", [("-$1,234.50", 123450), ("(12.00)", 1200), ("-0.01", 1), ("$-3.10", 310)])
def test_money_formats_become_exact_cents(tmp_path, raw, deducted):
    res = load_payout(write(tmp_path, dd_csv(dd_row("DD-1", amount=f'"{raw}"'))))
    assert res.deductions[0].amount_cents == deducted


@pytest.mark.parametrize("raw", ["12.00", "0.00"])
def test_non_negative_amounts_are_not_deductions(tmp_path, raw):
    assert load_payout(write(tmp_path, dd_csv(dd_row("DD-1", amount=raw)))).deductions == []


def test_non_refund_rows_are_ignored(tmp_path):
    res = load_payout(write(tmp_path, dd_csv(dd_row("DD-1", typ="Order", amount="-5.00"), dd_row("DD-2"))))
    assert [d.order_id for d in res.deductions] == ["DD-2"]


def test_large_file_parses_and_triages_quickly(tmp_path):
    rows = []
    for i in range(600):
        refund = i % 2 == 0
        rows.append(dd_row(f"DD-{i}", amount="-12.50" if refund else "20.00", typ="Refund" if refund else "Order",
                           customer=f"cust{i % 40}", item=f"Item {i % 25}"))
    p = write(tmp_path, dd_csv(*rows))
    t0 = time.perf_counter()
    res = load_payout(p)
    s = Session(tmp_path / "cases", TICKETS, TODAY,
                memory_dir=tmp_path / "mem")
    ranked = s.ingest(res.deductions)
    s.hero()
    elapsed = time.perf_counter() - t0
    assert len(res.deductions) == len(ranked) == 300 and not res.errors
    assert elapsed < 3.0, f"{elapsed:.2f}s for 300 refund rows"


# ---- through the API: every bad file is a clear 4xx before any model call is spent ------------------------
@pytest.fixture
def client(tmp_path, fix):
    cfg = Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY,
                   model_factory=lambda: PolicyChatModel())
    return TestClient(create_app(cfg))


def _start_with(client, content: bytes):
    up = client.post("/api/uploads", files={"file": ("x.csv", content, "text/csv")}).json()["upload_id"]
    return client.post("/api/runs", json={"upload_id": up})


@pytest.mark.parametrize("name,content,fragment", [
    ("empty", b"", "could not read"),
    ("headers only", dd_csv().encode(), "no refund deductions"),
    ("missing column", dd_csv(dd_row(), header=DD_HEADER.replace("Description", "Notes")).encode(), "Description"),
    ("grubhub", b"Grubhub Order #,Date,Issue\n1,2026-11-04,Missing\n", "could not recognise"),
    ("binary garbage", bytes(range(256)) * 20, "could not read"),
    ("all bad amounts", dd_csv(dd_row(amount="oops")).encode(), "no refund deductions"),
])
def test_api_refuses_unusable_files_cleanly(client, name, content, fragment):
    r = _start_with(client, content)
    assert r.status_code == 422, name
    assert fragment in r.json()["detail"], r.json()
