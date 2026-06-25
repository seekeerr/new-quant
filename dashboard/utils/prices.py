"""Latest prices from the existing parquet cache (read-only).

The dashboard never downloads. It joins held/target symbols against the most
recent close already present in `data/cache_bhav/adj_close.parquet`, which the
existing daily-pull / bhavcopy workflow keeps fresh.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import paths

try:
    import streamlit as st

    _cache = st.cache_data
except Exception:  # pragma: no cover
    def _cache(*dargs, **dkwargs):
        def deco(fn):
            return fn

        return deco


@_cache(show_spinner=False)
def _latest_row(_mtime: float):
    """(last_date, last_close_series) from the price cache, or (None, empty)."""
    if not paths.PRICE_CACHE.exists():
        return None, pd.Series(dtype=float)
    try:
        df = pd.read_parquet(paths.PRICE_CACHE)
        if df.empty:
            return None, pd.Series(dtype=float)
        df = df.sort_index()
        last_date = df.index[-1]
        # ffill so a single missing print falls back to the prior close.
        last_close = df.ffill().iloc[-1]
        return pd.Timestamp(last_date), last_close.dropna()
    except Exception:
        return None, pd.Series(dtype=float)


def latest_prices() -> pd.Series:
    """Series symbol -> latest close. Empty if the cache is unavailable."""
    _, close = _latest_row(paths.mtime(paths.PRICE_CACHE))
    return close


def last_close_date() -> Optional[pd.Timestamp]:
    """Date of the most recent close in the cache, or None."""
    date, _ = _latest_row(paths.mtime(paths.PRICE_CACHE))
    return date


def price_for(symbol: str) -> Optional[float]:
    """Latest close for one symbol, or None if not in the cache."""
    close = latest_prices()
    if symbol in close.index:
        val = close[symbol]
        return float(val) if pd.notna(val) else None
    return None
