from datetime import date

import pytest

from reclaim.dates import days_left, filing_deadline
from reclaim.money import fmt_cents, parse_cents, weighted_cents
from reclaim.schemas import Platform


@pytest.mark.parametrize("raw,cents", [
    ("$1,234.50", 123450), ("-$3.10", -310), ("(12.00)", -1200), ("-18.75", -1875),
    ("12", 1200), (" 0.07 ", 7), ("$0.1", 10),
])
def test_parse_cents(raw, cents):
    assert parse_cents(raw) == cents


@pytest.mark.parametrize("bad", ["", "abc", None])
def test_parse_cents_rejects(bad):
    with pytest.raises(ValueError):
        parse_cents(bad)


def test_no_float_drift():
    assert sum(parse_cents("0.10") for _ in range(10)) == 100


def test_fmt_and_weighted():
    assert fmt_cents(123456) == "$1,234.56"
    assert fmt_cents(-5) == "-$0.05"
    assert weighted_cents(4200, 5000) == 2100
    assert weighted_cents(1, 5000) == 1  # rounds half up


def test_deadlines():
    assert filing_deadline(Platform.DOORDASH, date(2026, 11, 10)) == date(2026, 11, 24)
    assert filing_deadline(Platform.UBEREATS, date(2026, 11, 12)) == date(2026, 12, 12)


def test_days_left_boundaries():
    dl = date(2026, 11, 24)
    assert days_left(dl, date(2026, 11, 24)) == 0   # last day still filable
    assert days_left(dl, date(2026, 11, 25)) == -1  # expired
