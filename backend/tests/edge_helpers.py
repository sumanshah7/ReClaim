"""Builders shared by the edge-case tests."""
from __future__ import annotations

from datetime import date, datetime

from reclaim.ingest.common import customer_key
from reclaim.schemas import ClaimReason, Deduction, Platform

DD_HEADER = "Store,Order ID,Order Time,Pickup Time,Transaction Type,Description,Customer,Item,Amount,Payout Date"


def dd_row(order="DD-1", amount="-12.00", reason="Missing item refund", item="Green Smoothie", customer="Ann",
           payout="2026-11-10", typ="Refund", pickup="2026-11-04 13:29", otime="2026-11-04 13:10") -> str:
    return f"Test Shop,{order},{otime},{pickup},{typ},{reason},{customer},{item},{amount},{payout}"


def dd_csv(*rows: str, header: str = DD_HEADER, eol: str = "\n") -> str:
    return eol.join([header, *rows]) + eol


def write(tmp_path, text: str | bytes, name="payout.csv"):
    p = tmp_path / name
    p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return p


def ded(order="DD-1", cents=2000, reason=ClaimReason.MISSING_ITEM, payout=date(2026, 11, 10), item="Green Smoothie",
        customer="Ann", platform=Platform.DOORDASH, row=2) -> Deduction:
    return Deduction(id=f"{platform.value}:{order}", platform=platform, order_id=order,
                     order_ts=datetime(2026, 11, 4, 13, 10), pickup_ts=datetime(2026, 11, 4, 13, 29),
                     amount_cents=cents, reason=reason, claimed_item=item, customer_key=customer_key(customer),
                     payout_date=payout, source_row=row)
