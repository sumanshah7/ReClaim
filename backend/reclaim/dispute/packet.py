from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..money import fmt_cents
from ..schemas import Case, Dispute


def write_packet(case_dir: Path, case: Case, dispute: Dispute, now: datetime) -> Path:
    """The platforms have no dispute API, so 'send' produces a ready-to-submit packet and a sent log."""
    d = case.deduction
    lines = [
        f"# Dispute packet: order {d.order_id} ({d.platform.value})",
        "",
        f"Amount deducted: {fmt_cents(d.amount_cents)}",
        f"Reason given: {d.reason.value.replace('_', ' ')}" + (f" ({d.claimed_item})" if d.claimed_item else ""),
        f"Filing deadline: {case.deadline.isoformat()}",
        "",
        "## Dispute text",
        dispute.body.strip(),
        "",
        "## Evidence",
    ]
    by_id = {e.id: e for e in case.evidence}
    for eid in dispute.cited_evidence_ids:
        e = by_id[eid]
        lines.append(f"- [{e.id}] {e.summary} (source: {e.source_ref})")
    path = case_dir / "packet.md"
    path.write_text("\n".join(lines) + "\n")
    (case_dir / "sent.json").write_text(json.dumps({"case_id": case.id, "sent_at": now.isoformat(),
                                                     "channel": "packet (no platform API)"}, indent=2))
    return path
