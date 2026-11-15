"""Deterministic guard for rule 4: dispute drafts state facts and never accuse the customer."""
from __future__ import annotations

import re

BANNED = [
    "lied", "lie ", "lying", "liar", "fraud", "fraudulent", "false claim", "false report", "fake", "scam",
    "dishonest", "cheat", "steal", "stole", "theft", "abuse", "abusing", "bad faith", "pretend", "fabricat",
    "suspicious customer", "the customer is wrong", "customer is lying",
]
_PATTERN = re.compile("|".join(re.escape(b) for b in BANNED), re.I)


def lint_dispute(body: str) -> list[str]:
    """Return a list of violations (empty means the draft passes)."""
    problems = [f"accusatory or loaded wording: '{m.group(0).strip()}'" for m in _PATTERN.finditer(body)]
    if len(body.strip()) < 40:
        problems.append("draft is too short to state the facts")
    return problems
