from __future__ import annotations

from pathlib import Path

from ..schemas import Platform
from ._csvbase import parse_payout_csv
from .common import ParseResult

REQUIRED = ["Order UUID", "Order Time", "Handoff Time", "Event", "Reason", "Customer", "Item", "Total Adjustment", "Payout Date"]
COLS = dict(order_id="Order UUID", order_ts="Order Time", pickup_ts="Handoff Time", reason="Reason",
            customer="Customer", item="Item", amount="Total Adjustment", payout_date="Payout Date")


def parse(path: str | Path) -> ParseResult:
    return parse_payout_csv(
        path, platform=Platform.UBEREATS, required=REQUIRED, cols=COLS,
        is_deduction=lambda r: r["Event"].strip().lower().startswith("refund"),
    )
