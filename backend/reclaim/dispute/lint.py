"""Deterministic guard for rule 4: dispute drafts state facts and never accuse the customer."""
from __future__ import annotations

import re

BANNED = [
    "lied", "lie ", "lying", "liar", "fraud", "fraudulent", "false claim", "false report", "fake", "scam",
    "dishonest", "cheat", "steal", "stole", "theft", "abuse", "abusing", "bad faith", "pretend", "fabricat",
    "suspicious customer", "the customer is wrong", "customer is lying",
]
_PATTERN = re.compile("|".join(re.escape(b) for b in BANNED), re.I)


def lint_dispute(body: str, ignore: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Return a list of violations (empty means the draft passes). `ignore` lists product names that may be quoted
    as written ("Cheat Day Burger"): they are blanked out before the wording check, so an item's own name never
    blocks a dispute, while accusations around it still do."""
    scan = body
    for name in sorted({n for n in ignore if n and n.strip()}, key=len, reverse=True):
        scan = re.sub(re.escape(name.strip()), " ", scan, flags=re.I)
    problems = [f"accusatory or loaded wording: '{m.group(0).strip()}'" for m in _PATTERN.finditer(scan)]
    if len(body.strip()) < 40:
        problems.append("draft is too short to state the facts")
    return problems
