from __future__ import annotations

from pathlib import Path

from ..schemas import Platform
from ._csvbase import parse_payout_csv
from .common import ParseResult

REQUIRED = ["Order ID", "Order Time", "Pickup Time", "Transaction Type", "Description", "Customer", "Item", "Amount", "Payout Date"]
COLS = dict(order_id="Order ID", order_ts="Order Time", pickup_ts="Pickup Time", reason="Description",
            customer="Customer", item="Item", amount="Amount", payout_date="Payout Date")


def parse(path: str | Path) -> ParseResult:
    return parse_payout_csv(
        path, platform=Platform.DOORDASH, required=REQUIRED, cols=COLS,
        is_deduction=lambda r: r["Transaction Type"].strip().lower() in {"refund", "error charge"},
    )
