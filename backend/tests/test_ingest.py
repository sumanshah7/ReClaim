import pytest

from reclaim.ingest import doordash, ubereats
from reclaim.ingest.normalize import detect_platform, load_payout
from reclaim.schemas import ClaimReason, Platform


def test_doordash_golden(fix):
    r = doordash.parse(fix / "doordash_payout.csv")
    assert len(r.deductions) == 9 and not r.errors
    d = next(x for x in r.deductions if x.order_id == "DD-48211")
    assert d.amount_cents == 4200 and d.reason == ClaimReason.MISSING_ITEM
    assert d.claimed_item == "Acai Bowl (Large)" and d.platform == Platform.DOORDASH
    assert d.pickup_ts.hour == 12 and d.pickup_ts.minute == 22
    assert "Alex" not in d.customer_key  # raw names are never stored
    other = next(x for x in r.deductions if x.order_id == "DD-48301")
    assert other.reason == ClaimReason.OTHER and other.claimed_item is None


def test_normal_orders_are_not_deductions(fix):
    ids = {d.order_id for d in doordash.parse(fix / "doordash_payout.csv").deductions}
    assert "DD-48200" not in ids


def test_ubereats_golden(fix):
    r = ubereats.parse(fix / "ubereats_payout.csv")
    assert [d.order_id for d in r.deductions] == ["UE-9a31", "UE-9a47", "UE-9b02"]
    assert r.deductions[0].amount_cents == 2430


def test_repeat_customer_shares_key(fix):
    ds = doordash.parse(fix / "doordash_payout.csv").deductions
    keys = [d.customer_key for d in ds if d.order_id in {"DD-48244", "DD-48251", "DD-48267"}]
    assert len(set(keys)) == 1


def test_detect_platform(fix):
    assert detect_platform(fix / "ubereats_payout.csv") == Platform.UBEREATS
    assert len(load_payout(fix / "doordash_payout.csv").deductions) == 9


def test_empty_file_is_error(tmp_path):
    p = tmp_path / "e.csv"; p.write_text("")
    with pytest.raises(ValueError):
        load_payout(p)


def test_missing_columns(tmp_path):
    p = tmp_path / "m.csv"; p.write_text("Order ID,Amount\nA,-1.00\n")
    with pytest.raises(ValueError):
        doordash.parse(p)


HEADER = "Store,Order ID,Order Time,Pickup Time,Transaction Type,Description,Customer,Item,Amount,Payout Date\n"


def test_bad_rows_reported_not_dropped_silently(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text(HEADER +
        "S,A1,not-a-date,,Refund,Missing item,X,Bowl,-5.00,2026-11-10\n"
        "S,A2,2026-11-03 12:00,,Refund,Missing item,X,Bowl,-5.00,2026-11-10\n"
        "S,A2,2026-11-03 12:00,,Refund,Missing item,X,Bowl,-5.00,2026-11-10\n"
        "S,A3,2026-11-03 12:00,,Refund,Missing item,X,Bowl,abc,2026-11-10\n")
    r = doordash.parse(p)
    assert [d.order_id for d in r.deductions] == ["A2"]
    assert len(r.errors) == 3


def test_header_only_is_empty(tmp_path):
    p = tmp_path / "h.csv"; p.write_text(HEADER)
    assert doordash.parse(p).deductions == []
