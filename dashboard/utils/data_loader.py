"""Graceful readers for every operational file.

Contract: **no reader ever raises on a missing/corrupt file.** Each returns a
safe empty value (empty DataFrame with the expected columns, or {} / None) so
pages can render a "no data yet" notice instead of a traceback.

Readers are cached on (path, mtime) so edits appear on the next refresh without
a stale cache, while repeated reads within a run stay cheap.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from . import paths

try:  # Streamlit is the runtime, but utils must import without it (for tests).
    import streamlit as st

    _cache = st.cache_data
except Exception:  # pragma: no cover - fallback no-op cache
    def _cache(*dargs, **dkwargs):
        def deco(fn):
            return fn

        return deco


# --- low-level safe readers -------------------------------------------------

def _read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a CSV, returning an empty frame with `columns` if missing/bad."""
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(path)
        if df.empty:
            return pd.DataFrame(columns=columns)
        return df
    except Exception:
        return pd.DataFrame(columns=columns)


# --- public loaders (cached on file mtime) ---------------------------------

@_cache(show_spinner=False)
def load_state(_mtime: float = 0.0) -> dict:
    """Portfolio state dict; {} if absent/unreadable."""
    if not paths.STATE_FILE.exists():
        return {}
    try:
        return json.loads(paths.STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


@_cache(show_spinner=False)
def load_holdings(_mtime: float = 0.0) -> pd.DataFrame:
    cols = ["symbol", "quantity", "cost_price", "entry_date"]
    df = _read_csv(paths.HOLDINGS_FILE, cols)
    if not df.empty:
        df["quantity"] = pd.to_numeric(df.get("quantity"), errors="coerce")
        df["cost_price"] = pd.to_numeric(df.get("cost_price"), errors="coerce")
    return df


@_cache(show_spinner=False)
def load_target(_mtime: float = 0.0) -> pd.DataFrame:
    cols = ["rank", "symbol", "score", "in_top10", "in_buffer20",
            "classification", "current_held"]
    return _read_csv(paths.TARGET_FILE, cols)


@_cache(show_spinner=False)
def load_rebalances(_mtime: float = 0.0) -> pd.DataFrame:
    cols = ["date", "num_holdings", "turnover_pct", "holdings_snapshot",
            "notes", "snapshot_id"]
    df = _read_csv(paths.REBALANCE_FILE, cols)
    if not df.empty and "date" in df:
        df = df.sort_values("date", ascending=False, ignore_index=True)
    return df


@_cache(show_spinner=False)
def load_trades(_mtime: float = 0.0) -> pd.DataFrame:
    cols = ["date", "symbol", "action", "quantity", "price", "costs", "notes"]
    df = _read_csv(paths.TRADE_LOG_FILE, cols)
    if not df.empty and "date" in df:
        df = df.sort_values("date", ascending=False, ignore_index=True)
    return df


@_cache(show_spinner=False)
def load_equity_curve(_mtime: float = 0.0) -> pd.Series:
    """Paper NAV indexed by date; empty Series if absent."""
    if not paths.EQUITY_FILE.exists():
        return pd.Series(dtype=float, name="portfolio_value")
    try:
        df = pd.read_csv(paths.EQUITY_FILE, parse_dates=["date"])
        s = df.set_index("date")["portfolio_value"].astype(float)
        return s.sort_index()
    except Exception:
        return pd.Series(dtype=float, name="portfolio_value")


@_cache(show_spinner=False)
def load_benchmark(_mtime: float = 0.0) -> pd.Series:
    """NIFTY 500 price index close, indexed by date; empty if absent."""
    if not paths.BENCHMARK_FILE.exists():
        return pd.Series(dtype=float, name="benchmark")
    try:
        df = pd.read_csv(paths.BENCHMARK_FILE, parse_dates=["Date"])
        return df.set_index("Date")["Close"].astype(float).sort_index()
    except Exception:
        return pd.Series(dtype=float, name="benchmark")


# --- convenience wrappers that inject the mtime cache key ------------------

def state() -> dict:
    return load_state(paths.mtime(paths.STATE_FILE))


def holdings() -> pd.DataFrame:
    return load_holdings(paths.mtime(paths.HOLDINGS_FILE))


def target() -> pd.DataFrame:
    return load_target(paths.mtime(paths.TARGET_FILE))


def rebalances() -> pd.DataFrame:
    return load_rebalances(paths.mtime(paths.REBALANCE_FILE))


def trades() -> pd.DataFrame:
    return load_trades(paths.mtime(paths.TRADE_LOG_FILE))


def equity_curve() -> pd.Series:
    return load_equity_curve(paths.mtime(paths.EQUITY_FILE))


def benchmark() -> pd.Series:
    return load_benchmark(paths.mtime(paths.BENCHMARK_FILE))


def list_audit_packages() -> list[str]:
    """Sub-directories under paper_trading/audit/, newest first; [] if none."""
    if not paths.AUDIT_DIR.exists():
        return []
    try:
        return sorted(
            (p.name for p in paths.AUDIT_DIR.iterdir() if p.is_dir()),
            reverse=True,
        )
    except Exception:
        return []


def audit_package_files(package: str) -> list[Path]:
    """Files inside a given audit package, or [] if the package is missing."""
    pkg = paths.AUDIT_DIR / package
    if not pkg.exists():
        return []
    try:
        return sorted(p for p in pkg.rglob("*") if p.is_file())
    except Exception:
        return []


def read_text(path: Path, max_bytes: int = 200_000) -> Optional[str]:
    """Read a small text file for preview; None if unreadable/too big/binary."""
    try:
        if path.stat().st_size > max_bytes:
            return f"(file too large to preview: {path.stat().st_size:,} bytes)"
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
