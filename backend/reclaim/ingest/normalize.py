from __future__ import annotations

from pathlib import Path

from ..schemas import Platform
from . import doordash, ubereats
from .common import ParseResult

_PARSERS = {Platform.DOORDASH: doordash.parse, Platform.UBEREATS: ubereats.parse}


def detect_platform(path: str | Path) -> Platform:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = fh.readline()
    if "Order UUID" in header:
        return Platform.UBEREATS
    if "Transaction Type" in header:
        return Platform.DOORDASH
    raise ValueError("could not recognise payout format (expected a DoorDash or Uber Eats CSV)")


def load_payout(path: str | Path) -> ParseResult:
    return _PARSERS[detect_platform(path)](path)
