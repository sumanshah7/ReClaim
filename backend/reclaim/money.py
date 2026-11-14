"""Money math: integer cents only, Decimal for parsing. No floats (Constitution rule 7)."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CLEAN = re.compile(r"[^\d.\-()]")


def parse_cents(raw: str | int | float | Decimal | None) -> int:
    """Parse '$1,234.50', '(12.00)', '-$3.10', '12' into signed integer cents."""
    if raw is None:
        raise ValueError("empty money value")
    if isinstance(raw, int):
        return raw * 100
    s = str(raw).strip()
    if not s:
        raise ValueError("empty money value")
    neg = (s.startswith("(") and s.endswith(")")) or "-" in s
    cleaned = _CLEAN.sub("", s).replace("(", "").replace(")", "").lstrip("-")
    try:
        d = Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(f"unparseable money value: {raw!r}") from e
    cents = int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))
    return -cents if neg else cents


def fmt_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}${c // 100:,}.{c % 100:02d}"


def weighted_cents(cents: int, p_win_bp: int) -> int:
    """cents * probability, probability in basis points (0..10000), rounded half up."""
    return (cents * p_win_bp + 5000) // 10000
