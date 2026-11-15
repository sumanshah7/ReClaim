"""Generate SYNTHETIC samples for two restaurants the project has been discussed with.

  Chutney (Montclair, NJ)           DoorDash, momo-focused menu
  Tandoori Flames (Parsippany, NJ)  Uber Eats, biryani and tandoori menu

EVERYTHING here is invented: orders, customers, amounts and ticket images. Menu items are plausible examples of the
food those places serve, not their real menus or prices. This is not data from either restaurant.
Run: backend/.venv/bin/python scripts/gen_restaurant_fixtures.py   (safe to re-run; it never touches existing samples)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
TICKETS = FIX / "tickets"

CHUTNEY = "Chutney - Montclair NJ (synthetic)"
TANDOORI = "Tandoori Flames - Parsippany NJ (synthetic)"

# (order_id, ordered, ready, pickup, customer, items_on_ticket, claimed_item, reason, amount, payout_date, has_ticket)
CHUTNEY_ROWS = [
    ("DD-51102", "2026-11-03 19:05", "2026-11-03 19:24", "2026-11-03 19:27", "Rohan P", ["Chicken Momo Party Tray", "Mango Lassi"], "Chicken Momo Party Tray", "Missing item", "46.80", "2026-11-10", False),
    ("DD-51115", "2026-11-04 12:40", "2026-11-04 12:55", "2026-11-04 12:58", "Anita B", ["Jhol Momo", "Veg Momo (Steamed)"], "Jhol Momo", "Missing item", "17.50", "2026-11-10", True),
    ("DD-51123", "2026-11-05 18:20", "2026-11-05 18:36", "2026-11-05 18:40", "Kiran T", ["Veg Momo (Fried)", "Samosa Chaat"], "Veg Momo (Fried)", "Missing item", "14.25", "2026-11-10", True),
    ("DD-51131", "2026-11-06 19:15", "2026-11-06 19:31", "2026-11-06 19:34", "Kiran T", ["Chicken Momo (Steamed)", "Chili Momo"], "Chicken Momo (Steamed)", "Wrong item", "19.00", "2026-11-10", True),
    ("DD-51140", "2026-11-07 13:05", "2026-11-07 13:18", "2026-11-07 13:21", "Kiran T", ["Chili Momo"], "Chili Momo", "Missing item", "13.75", "2026-11-10", True),
    ("DD-51152", "2026-11-07 20:10", "2026-11-07 20:26", "2026-11-07 20:29", "Dev M", ["Veg Momo (Steamed)", "Samosa Chaat"], "Chicken Thukpa", "Missing item", "28.40", "2026-11-10", True),
    ("DD-51160", "2026-11-08 14:00", "2026-11-08 14:12", "2026-11-08 14:17", "Sunita L", ["Chicken Momo (Pan-Fried)", "Mango Lassi"], "Mango Lassi", "Missing item", "9.50", "2026-11-10", True),
    ("DD-51171", "2026-11-08 21:00", "2026-11-08 21:14", "2026-11-08 21:18", "Pooja R", ["Jhol Momo"], "", "Other", "11.00", "2026-11-10", True),
    ("DD-50980", "2026-10-17 18:30", "2026-10-17 18:46", "2026-10-17 18:50", "Arjun S", ["Chicken Momo (Steamed)"], "Chicken Momo (Steamed)", "Missing item", "22.00", "2026-10-20", True),
]
CHUTNEY_NORMAL = [
    ("DD-51100", "2026-11-03 11:50", "24.50", "2026-11-10"), ("DD-51110", "2026-11-04 12:10", "31.00", "2026-11-10"),
    ("DD-51120", "2026-11-05 12:45", "18.75", "2026-11-10"), ("DD-51135", "2026-11-06 19:50", "42.20", "2026-11-10"),
    ("DD-51148", "2026-11-07 18:40", "27.90", "2026-11-10"), ("DD-51158", "2026-11-08 13:20", "15.60", "2026-11-10"),
]
TANDOORI_ROWS = [
    ("UE-tf01a", "2026-11-04 18:10", "2026-11-04 18:34", "2026-11-04 18:38", "Vikram J", ["Chicken Biryani (Family Size)", "Garlic Naan"], "Chicken Biryani (Family Size)", "Missing item", "52.00", "2026-11-12", False),
    ("UE-tf02b", "2026-11-05 19:00", "2026-11-05 19:22", "2026-11-05 19:26", "Neha K", ["Lamb Biryani", "Raita"], "Lamb Biryani", "Missing item", "21.50", "2026-11-12", True),
    ("UE-tf03c", "2026-11-05 20:15", "2026-11-05 20:33", "2026-11-05 20:36", "Meera V", ["Garlic Naan", "Butter Chicken"], "Garlic Naan", "Missing item", "15.00", "2026-11-12", True),
    ("UE-tf04d", "2026-11-06 12:30", "2026-11-06 12:50", "2026-11-06 12:53", "Meera V", ["Veg Biryani", "Mango Lassi"], "Veg Biryani", "Wrong item", "18.25", "2026-11-12", True),
    ("UE-tf05e", "2026-11-07 19:40", "2026-11-07 19:58", "2026-11-07 20:02", "Meera V", ["Samosa (2 pc)", "Chicken Tikka"], "Samosa (2 pc)", "Missing item", "12.75", "2026-11-12", True),
    ("UE-tf06f", "2026-11-08 18:25", "2026-11-08 18:47", "2026-11-08 18:50", "Imran H", ["Paneer Tikka Masala", "Garlic Naan"], "Butter Chicken", "Missing item", "31.20", "2026-11-12", True),
    ("UE-tf07g", "2026-11-09 13:15", "2026-11-09 13:32", "2026-11-09 13:38", "Tara G", ["Chicken Tikka", "Basmati Rice"], "Chicken Tikka", "Missing item", "26.80", "2026-11-12", True),
    ("UE-tf08h", "2026-11-09 20:05", "2026-11-09 20:21", "2026-11-09 20:25", "Rahul D", ["Gulab Jamun (2 pc)", "Mango Lassi"], "Gulab Jamun (2 pc)", "Missing item", "9.00", "2026-11-12", True),
    ("UE-tf09i", "2026-11-10 19:30", "2026-11-10 19:48", "2026-11-10 19:52", "Sana F", ["Lamb Biryani"], "", "Other", "14.00", "2026-11-12", True),
    ("UE-tf00z", "2026-10-06 18:00", "2026-10-06 18:20", "2026-10-06 18:24", "Omar Q", ["Chicken Biryani"], "Chicken Biryani", "Missing item", "24.00", "2026-10-10", True),
]


RESTAURANT_DOC = (
    "## Restaurant samples\n\n"
    "Two samples are named after restaurants the project has been discussed with: **Chutney (Montclair, NJ)**, a momo-focused DoorDash "
    "sample (`chutney_montclair_doordash_payout.csv`), and **Tandoori Flames (Parsippany, NJ)**, a biryani and tandoori Uber Eats sample "
    "(`tandoori_flames_parsippany_ubereats_payout.csv`). The orders, customers, amounts, prices and ticket images are invented, and the menu "
    "items are plausible examples, not those restaurants' real menus. This is not data from either restaurant and says nothing about how "
    "either of them operates.\n"
)


def iso(s: str) -> str:
    return s.replace(" ", "T") + ":00"


def render_ticket(shop: str, order_id: str, placed: str, ready: str, items: list[str]) -> None:
    img = Image.new("RGB", (460, 170 + 34 * len(items)), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 17)
    except OSError:
        f = ImageFont.load_default()
    y = 12
    for line in [shop.replace(" (synthetic)", ""), f"ORDER {order_id}", f"PLACED {placed[11:]}   READY {ready[11:]}", "-" * 32]:
        d.text((16, y), line, fill="black", font=f); y += 28
    for it in items:
        d.text((16, y), f"1x {it}", fill="black", font=f); y += 30
    d.text((16, y + 10), "SYNTHETIC FIXTURE", fill=(180, 0, 0), font=f)
    img.save(TICKETS / f"{order_id}.png")


def main() -> None:
    TICKETS.mkdir(parents=True, exist_ok=True)
    existing = {t["order_id"]: t for t in json.loads((FIX / "tickets.json").read_text())}
    new_tickets: dict[str, dict] = {}

    def add_ticket(shop, oid, ot, rt, items, conf):
        render_ticket(shop, oid, ot, rt, items)
        new_tickets[oid] = {"order_id": oid, "items": items, "placed_ts": iso(ot), "ready_ts": iso(rt),
                            "image_path": f"fixtures/tickets/{oid}.png", "extraction_confidence": conf}

    with open(FIX / "chutney_montclair_doordash_payout.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Store", "Order ID", "Order Time", "Pickup Time", "Transaction Type", "Description", "Customer", "Item", "Amount", "Payout Date"])
        for oid, ot, amt, pd in CHUTNEY_NORMAL:
            w.writerow([CHUTNEY, oid, ot, "", "Order", "Order payout", "", "", amt, pd])
        for oid, ot, rt, pt, cust, items, claimed, reason, amt, pd, has in CHUTNEY_ROWS:
            w.writerow([CHUTNEY, oid, ot, pt, "Refund", f"Customer refund - {reason}", cust, claimed, f"-{amt}", pd])
            if has:
                add_ticket(CHUTNEY, oid, ot, rt, items, 0.96)

    with open(FIX / "tandoori_flames_parsippany_ubereats_payout.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Order UUID", "Order Time", "Handoff Time", "Event", "Reason", "Customer", "Item", "Total Adjustment", "Payout Date"])
        for oid, ot, rt, pt, cust, items, claimed, reason, amt, pd, has in TANDOORI_ROWS:
            w.writerow([oid, ot, pt, "Refund - Order Issue", reason, cust, claimed, f"-${amt}", pd])
            if has:
                add_ticket(TANDOORI, oid, ot, rt, items, 0.95)

    existing.update(new_tickets)
    (FIX / "tickets.json").write_text(json.dumps(list(existing.values()), indent=2))

    (FIX / "samples.json").write_text(json.dumps([
        {"file": "doordash_payout.csv", "label": "Demo Bowl Shop", "platform": "DoorDash", "note": "synthetic"},
        {"file": "ubereats_payout.csv", "label": "Demo sample", "platform": "Uber Eats", "note": "synthetic"},
        {"file": "chutney_montclair_doordash_payout.csv", "label": "Chutney, Montclair NJ", "platform": "DoorDash", "note": "synthetic, momo menu"},
        {"file": "tandoori_flames_parsippany_ubereats_payout.csv", "label": "Tandoori Flames, Parsippany NJ", "platform": "Uber Eats", "note": "synthetic, biryani and tandoori menu"},
    ], indent=2))

    note = FIX / "SYNTHETIC.md"
    text = note.read_text()
    marker = "## Restaurant samples"
    if marker not in text:
        note.write_text(text.rstrip() + "\n\n" + RESTAURANT_DOC)
    print(f"wrote {len(CHUTNEY_ROWS)} Chutney refunds, {len(TANDOORI_ROWS)} Tandoori Flames refunds, {len(new_tickets)} tickets")


if __name__ == "__main__":
    main()
