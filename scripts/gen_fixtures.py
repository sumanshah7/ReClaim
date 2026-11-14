"""Generate SYNTHETIC fixtures: payout CSVs, ticket PNGs and the cached ticket extraction.

Everything here is invented. Column layouts are plausible stand-ins, not copies of real
platform exports. Run: backend/.venv/bin/python scripts/gen_fixtures.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
TICKETS = FIX / "tickets"
SHOP = "Demo Bowl Shop (synthetic)"

# (order_id, order_dt, ready_dt, pickup_dt, customer, items_on_ticket, claimed_item, reason, amount, payout_date, has_ticket)
DD = [
    ("DD-48211", "2026-11-03 12:04", "2026-11-03 12:19", "2026-11-03 12:22", "Alex R", ["Acai Bowl (Large)", "Cold Brew"], "Acai Bowl (Large)", "Missing item", "42.00", "2026-11-10", False),
    ("DD-48230", "2026-11-04 13:10", "2026-11-04 13:24", "2026-11-04 13:29", "Maria S", ["Green Smoothie", "Granola Cup"], "Green Smoothie", "Missing item", "18.75", "2026-11-10", True),
    ("DD-48244", "2026-11-05 18:31", "2026-11-05 18:46", "2026-11-05 18:50", "Jordan K", ["Granola Add-on", "Fruit Bowl"], "Granola Add-on", "Missing item", "14.25", "2026-11-10", True),
    ("DD-48251", "2026-11-06 19:02", "2026-11-06 19:15", "2026-11-06 19:18", "Jordan K", ["Protein Bowl", "Chia Pudding"], "Chia Pudding", "Wrong item", "21.00", "2026-11-10", True),
    ("DD-48267", "2026-11-07 12:40", "2026-11-07 12:52", "2026-11-07 12:55", "Jordan K", ["Peanut Butter Bowl"], "Peanut Butter Bowl", "Missing item", "16.50", "2026-11-10", True),
    ("DD-48280", "2026-11-07 14:15", "2026-11-07 14:26", "2026-11-07 14:31", "Priya N", ["Fruit Bowl", "Honey Drizzle"], "Honey Drizzle", "Missing item", "9.50", "2026-11-10", True),
    ("DD-48290", "2026-11-08 17:20", "2026-11-08 17:35", "2026-11-08 17:39", "Sam T", ["Fruit Bowl", "Green Smoothie"], "Protein Bowl", "Missing item", "27.40", "2026-11-10", True),
    ("DD-48301", "2026-11-08 20:05", "2026-11-08 20:20", "2026-11-08 20:24", "Lee W", ["Acai Bowl (Small)"], "", "Other", "12.00", "2026-11-10", True),
    ("DD-47990", "2026-10-17 12:00", "2026-10-17 12:14", "2026-10-17 12:18", "Chris D", ["Acai Bowl (Large)"], "Acai Bowl (Large)", "Missing item", "19.00", "2026-10-20", True),
]
DD_NORMAL = [
    ("DD-48200", "2026-11-03 11:30", "21.50", "2026-11-10"),
    ("DD-48215", "2026-11-03 12:30", "34.00", "2026-11-10"),
    ("DD-48222", "2026-11-04 12:00", "18.25", "2026-11-10"),
    ("DD-48258", "2026-11-06 13:15", "27.80", "2026-11-10"),
    ("DD-48275", "2026-11-07 13:50", "15.40", "2026-11-10"),
]
UE = [
    ("UE-9a31", "2026-11-05 12:15", "2026-11-05 12:28", "2026-11-05 12:33", "Dana P", ["Acai Bowl (Large)", "Honey Drizzle"], "Honey Drizzle", "Missing item", "24.30", "2026-11-12", True),
    ("UE-9a47", "2026-11-06 18:05", "2026-11-06 18:20", "2026-11-06 18:22", "Eli M", ["Protein Bowl"], "Fruit Bowl", "Wrong item", "11.80", "2026-11-12", True),
    ("UE-9b02", "2026-11-09 13:00", "2026-11-09 13:12", "2026-11-09 13:16", "Noor A", ["Green Smoothie", "Fruit Bowl"], "Green Smoothie", "Missing item", "33.00", "2026-11-12", False),
]


def iso(s: str) -> str:
    return s.replace(" ", "T") + ":00"


def render_ticket(order_id, placed, ready, items):
    img = Image.new("RGB", (420, 160 + 34 * len(items)), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 18)
    except OSError:
        f = ImageFont.load_default()
    y = 12
    for line in [SHOP, f"ORDER {order_id}", f"PLACED {placed[11:]}   READY {ready[11:]}", "-" * 30]:
        d.text((16, y), line, fill="black", font=f); y += 28
    for it in items:
        d.text((16, y), f"1x {it}", fill="black", font=f); y += 30
    d.text((16, y + 10), "SYNTHETIC FIXTURE", fill=(180, 0, 0), font=f)
    img.save(TICKETS / f"{order_id}.png")


def main():
    TICKETS.mkdir(parents=True, exist_ok=True)
    tickets = []
    with open(FIX / "doordash_payout.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Store", "Order ID", "Order Time", "Pickup Time", "Transaction Type", "Description", "Customer", "Item", "Amount", "Payout Date"])
        for oid, ot, amt, pd in DD_NORMAL:
            w.writerow([SHOP, oid, ot, "", "Order", "Order payout", "", "", amt, pd])
        for oid, ot, rt, pt, cust, items, claimed, reason, amt, pd, has in DD:
            w.writerow([SHOP, oid, ot, pt, "Refund", f"Customer refund - {reason}", cust, claimed, f"-{amt}", pd])
            if has:
                render_ticket(oid, ot, rt, items)
                tickets.append({"order_id": oid, "items": items, "placed_ts": iso(ot), "ready_ts": iso(rt),
                                "image_path": f"fixtures/tickets/{oid}.png", "extraction_confidence": 0.97})
    with open(FIX / "ubereats_payout.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Order UUID", "Order Time", "Handoff Time", "Event", "Reason", "Customer", "Item", "Total Adjustment", "Payout Date"])
        for oid, ot, rt, pt, cust, items, claimed, reason, amt, pd, has in UE:
            w.writerow([oid, ot, pt, "Refund - Order Issue", reason, cust, claimed, f"-${amt}", pd])
            if has:
                render_ticket(oid, ot, rt, items)
                tickets.append({"order_id": oid, "items": items, "placed_ts": iso(ot), "ready_ts": iso(rt),
                                "image_path": f"fixtures/tickets/{oid}.png", "extraction_confidence": 0.95})
    (FIX / "tickets.json").write_text(json.dumps(tickets, indent=2))
    (FIX / "SYNTHETIC.md").write_text(
        "# Synthetic fixtures\n\nEvery file in this folder is invented for the demo. Names, orders, amounts "
        "and ticket images are fake. Column layouts are plausible stand-ins, not copies of real platform "
        "exports. They are not data from Playa Bowls, Chutney or any real restaurant.\n")
    print(f"wrote {len(DD)} DoorDash refunds, {len(UE)} Uber Eats refunds, {len(tickets)} tickets")


if __name__ == "__main__":
    main()
