"""Display helpers: rupee / percent / date formatting and value-based colors.

Kept UI-free (returns plain strings) so it is reusable and testable.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

DASH = "—"


def _is_missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def rupees(value: Optional[float], decimals: int = 0) -> str:
    """Indian-style ₹ formatting (lakh/crore grouping)."""
    if _is_missing(value):
        return DASH
    neg = value < 0
    value = abs(float(value))
    whole = f"{value:.{decimals}f}"
    if "." in whole:
        int_part, frac = whole.split(".")
        frac = "." + frac
    else:
        int_part, frac = whole, ""
    # Indian grouping: last 3 digits, then groups of 2.
    if len(int_part) > 3:
        head, tail = int_part[:-3], int_part[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        int_part = ",".join(groups) + "," + tail
    sign = "-" if neg else ""
    return f"{sign}₹{int_part}{frac}"


def pct(value: Optional[float], decimals: int = 1) -> str:
    """Fraction -> percent string. 0.123 -> '12.3%'."""
    if _is_missing(value):
        return DASH
    return f"{value * 100:.{decimals}f}%"


def signed_pct(value: Optional[float], decimals: int = 1) -> str:
    if _is_missing(value):
        return DASH
    return f"{value * 100:+.{decimals}f}%"


def price(value: Optional[float]) -> str:
    if _is_missing(value):
        return DASH
    return f"₹{value:,.2f}"


def date_str(value) -> str:
    if _is_missing(value) or value in ("", "nan"):
        return DASH
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def pnl_color(value: Optional[float]) -> str:
    """Hex color for a P&L value: green up, red down, grey flat/missing."""
    if _is_missing(value) or value == 0:
        return "#888888"
    return "#16c784" if value > 0 else "#ea3943"


def classification_color(label: str) -> str:
    return {
        "BUY": "#16c784",
        "SELL": "#ea3943",
        "HOLD": "#3b82f6",
    }.get(str(label).upper(), "#888888")
