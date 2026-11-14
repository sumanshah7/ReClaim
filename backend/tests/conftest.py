from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "fixtures"
TODAY = date(2026, 11, 14)


@pytest.fixture
def fix():
    return FIX


@pytest.fixture
def today():
    return TODAY
