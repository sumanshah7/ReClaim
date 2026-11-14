from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

from ..money import parse_cents
from ..schemas import Deduction, Platform
from .common import ParseResult, customer_key, map_reason, parse_day, parse_dt


def parse_payout_csv(
    path: str | Path,
    *,
    platform: Platform,
    required: list[str],
    is_deduction: Callable[[dict], bool],
    cols: dict[str, str],
) -> ParseResult:
    """cols maps logical names (order_id, order_ts, pickup_ts, reason, customer, item, amount, payout_date)
    to the platform's header names."""
    res = ParseResult()
    seen: set[tuple] = set()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{platform.value} payout is missing columns: {missing}")
        for i, row in enumerate(reader, start=2):  # header is line 1
            try:
                if not is_deduction(row):
                    continue
                cents = parse_cents(row[cols["amount"]])
                if cents >= 0:
                    continue  # not a deduction
                key = (row[cols["order_id"]], cents, row[cols["reason"]])
                if key in seen:
                    res.errors.append(f"row {i}: duplicate of an earlier row, ignored")
                    continue
                seen.add(key)
                pickup_raw = row.get(cols["pickup_ts"], "").strip()
                item = row.get(cols["item"], "").strip() or None
                res.deductions.append(
                    Deduction(
                        id=f"{platform.value}:{row[cols['order_id']]}",
                        platform=platform,
                        order_id=row[cols["order_id"]],
                        order_ts=parse_dt(row[cols["order_ts"]]),
                        pickup_ts=parse_dt(pickup_raw) if pickup_raw else None,
                        amount_cents=-cents,
                        reason=map_reason(row[cols["reason"]]),
                        claimed_item=item,
                        customer_key=customer_key(row[cols["customer"]] or "unknown"),
                        payout_date=parse_day(row[cols["payout_date"]]),
                        source_row=i,
                    )
                )
            except (ValueError, KeyError) as e:
                res.errors.append(f"row {i}: {e}")
    return res
