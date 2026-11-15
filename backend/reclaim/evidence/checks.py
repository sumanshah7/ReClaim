"""Deterministic evidence helpers. Every Evidence cites a source_ref (rule 2)."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import timedelta
from pathlib import Path

from ..schemas import ClaimReason, Deduction, Evidence, EvidenceKind, Ticket

MAX_HANDOFF_GAP = timedelta(minutes=30)
MIN_EXTRACTION_CONFIDENCE = 0.6


log = logging.getLogger(__name__)


def load_tickets(path: str | Path) -> dict[str, Ticket]:
    """A damaged file is a clear error. A damaged entry only costs that one order its ticket (it is then reported as
    'no ticket on file'), never the whole run."""
    try:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, list):
            raise ValueError("expected a list of tickets")
    except (OSError, ValueError) as e:      # JSONDecodeError is a ValueError
        raise ValueError(f"the tickets file could not be read ({type(e).__name__}: {str(e)[:120]})") from e
    out: dict[str, Ticket] = {}
    for entry in data:
        try:
            t = Ticket(**entry)
            out[t.order_id] = t
        except Exception as e:  # noqa: BLE001 - pydantic and type errors alike
            log.warning("skipping unreadable ticket entry %r: %s", (entry or {}).get("order_id") if isinstance(entry, dict) else entry, e)
    return out


def _norm(s: str) -> str:
    """Case-, accent- and punctuation-insensitive form of an item name. Works for any script: accents are folded only
    on Latin letters, so non-Latin names (for example Devanagari) keep their letters instead of collapsing to ''."""
    s = unicodedata.normalize("NFKC", s).casefold()
    out: list[str] = []
    for ch in unicodedata.normalize("NFKD", s):
        if unicodedata.combining(ch) and out and out[-1].isascii():
            continue
        out.append(ch)
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFC", "".join(out))).strip()


def _related(claimed: str, listed: str) -> bool:
    """One name's words are all inside the other ('Chicken Momo' vs 'Chicken Momo (Steamed)')."""
    a, b = set(claimed.split()), set(listed.split())
    return bool(a and b) and (a <= b or b <= a)


def check_ticket_vs_claim(d: Deduction, ticket: Ticket | None) -> Evidence:
    if ticket is None:
        return Evidence(id=f"{d.order_id}:ticket_missing", kind=EvidenceKind.MISSING_ARTIFACT,
                        summary="No order ticket is on file for this order.",
                        source_ref=f"payout_row:{d.source_row}", supports=0, strength=0.0)
    if ticket.extraction_confidence < MIN_EXTRACTION_CONFIDENCE:
        return Evidence(id=f"{d.order_id}:ticket_illegible", kind=EvidenceKind.MISSING_ARTIFACT,
                        summary="The ticket photo could not be read reliably.",
                        source_ref=ticket.image_path or f"ticket:{d.order_id}", supports=0, strength=0.0)
    ref = ticket.image_path or f"ticket:{d.order_id}"
    if not d.claimed_item:
        return Evidence(id=f"{d.order_id}:claim_unspecified", kind=EvidenceKind.MISSING_ARTIFACT,
                        summary="The refund does not name a specific item to compare against the ticket.",
                        source_ref=f"payout_row:{d.source_row}", supports=0, strength=0.0)
    claimed = _norm(d.claimed_item)
    if not claimed:      # nothing comparable (for example an emoji-only name): do not match it against anything
        return Evidence(id=f"{d.order_id}:claim_unspecified", kind=EvidenceKind.MISSING_ARTIFACT,
                        summary="The refund does not name a specific item to compare against the ticket.",
                        source_ref=f"payout_row:{d.source_row}", supports=0, strength=0.0)
    listed = any(claimed == _norm(i) for i in ticket.items)
    similar = next((i for i in ticket.items if _norm(i) and _related(claimed, _norm(i))), None)
    if not listed and similar:   # partial match: say so and stay neutral rather than assert an omission
        return Evidence(id=f"{d.order_id}:{EvidenceKind.TICKET_LISTS_ITEM.value}", kind=EvidenceKind.TICKET_LISTS_ITEM,
                        summary=(f"The ticket for order {d.order_id} lists a similar item ('{similar}'), so the claimed "
                                 f"'{d.claimed_item}' cannot be matched exactly."),
                        source_ref=ref, supports=0, strength=0.2)
    if listed and d.reason == ClaimReason.MISSING_ITEM:
        # The ticket only proves the item was ordered, not that it was packed, so it does not support the restaurant
        # against a "missing item" claim. Neutral evidence cannot be cited as support in a dispute.
        return Evidence(id=f"{d.order_id}:{EvidenceKind.TICKET_LISTS_ITEM.value}", kind=EvidenceKind.TICKET_LISTS_ITEM,
                        summary=(f"The ticket for order {d.order_id} lists '{d.claimed_item}', which shows the item was "
                                 "ordered but not that it was packed."),
                        source_ref=ref, supports=0, strength=0.2)
    if listed:
        return Evidence(id=f"{d.order_id}:{EvidenceKind.TICKET_LISTS_ITEM.value}", kind=EvidenceKind.TICKET_LISTS_ITEM,
                        summary=f"The ticket for order {d.order_id} lists '{d.claimed_item}'.",
                        source_ref=ref, supports=1, strength=0.5)
    return Evidence(id=f"{d.order_id}:{EvidenceKind.TICKET_OMITS_ITEM.value}", kind=EvidenceKind.TICKET_OMITS_ITEM,
                    summary=f"The ticket for order {d.order_id} does not list '{d.claimed_item}'. Items on ticket: {', '.join(ticket.items)}.",
                    source_ref=ref, supports=1, strength=0.8)


def check_pickup_timestamps(d: Deduction, ticket: Ticket | None) -> Evidence | None:
    """None when there is nothing to compare (the missing ticket is already recorded by the other check)."""
    if ticket is None or ticket.ready_ts is None or d.pickup_ts is None:
        return None
    ref = f"{d.order_id}:ready={ticket.ready_ts.isoformat()},pickup={d.pickup_ts.isoformat()}"
    gap = d.pickup_ts - ticket.ready_ts
    if gap < timedelta(0):
        return Evidence(id=f"{d.order_id}:{EvidenceKind.PICKUP_HANDOFF.value}", kind=EvidenceKind.PICKUP_HANDOFF,
                        summary="The recorded pickup time is earlier than the ticket's ready time.",
                        source_ref=ref, supports=-1, strength=0.6)
    minutes = int(gap.total_seconds() // 60)
    return Evidence(id=f"{d.order_id}:{EvidenceKind.PICKUP_HANDOFF.value}", kind=EvidenceKind.PICKUP_HANDOFF,
                    summary=f"The order was ready at {ticket.ready_ts:%H:%M} and picked up at {d.pickup_ts:%H:%M} ({minutes} min later).",
                    source_ref=ref, supports=1 if gap <= MAX_HANDOFF_GAP else 0, strength=0.5)


def check_repeat_claimant(d: Deduction, all_deductions: list[Deduction], threshold: int = 3) -> Evidence | None:
    same = [x for x in all_deductions if x.customer_key == d.customer_key]
    if len(same) < threshold:
        return None
    orders = ", ".join(sorted(x.order_id for x in same))
    return Evidence(id=f"{d.order_id}:{EvidenceKind.REPEAT_CLAIMANT.value}", kind=EvidenceKind.REPEAT_CLAIMANT,
                    summary=f"{len(same)} refund claims came from the same customer account in this payout period (orders {orders}).",
                    source_ref="payout_rows:" + ",".join(str(x.source_row) for x in sorted(same, key=lambda x: x.source_row)),
                    supports=1, strength=0.4)


def gather_evidence(d: Deduction, all_deductions: list[Deduction], tickets: dict[str, Ticket]) -> list[Evidence]:
    t = tickets.get(d.order_id)
    out = [check_ticket_vs_claim(d, t)]
    for ev in (check_pickup_timestamps(d, t), check_repeat_claimant(d, all_deductions)):
        if ev:
            out.append(ev)
    return out
