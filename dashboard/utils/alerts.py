"""Operational alert rules (read-only).

Maps the file-derived conditions in DASHBOARD_ARCHITECTURE.md §6 to a list of
alerts. Severity follows the architecture's HALT vs NOTIFY model. The dashboard
only *reports* these — it never blocks the pipeline or acts on them.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from . import data_loader as dl
from . import metrics, paths, prices

HALT = "HALT"
NOTIFY = "NOTIFY"

STALE_PRICE_SESSIONS = 5      # trading days of tolerance before data is "stale"
REBALANCE_WINDOW_DAYS = 5     # how early "rebalance due" starts notifying
WEIGHT_TOLERANCE = 0.01       # ±1.0% absolute off the 10% target


def _alert(severity: str, title: str, detail: str) -> dict:
    return {"severity": severity, "title": title, "detail": detail}


def evaluate() -> list[dict]:
    """Return a list of active alerts (possibly empty = all clear)."""
    out: list[dict] = []
    state = dl.state()
    mode = str(state.get("mode", "")).upper()
    holdings = dl.holdings()

    # --- Missing / stale price data -------------------------------------
    last_date = prices.last_close_date()
    if last_date is None:
        out.append(_alert(HALT, "Price cache missing",
                          f"No readable price cache at {paths.PRICE_CACHE.name}. "
                          "Run the data-acquisition workflow before trading."))
    else:
        # ~7 calendar days ≈ 5 trading sessions of slack.
        age_days = (pd.Timestamp(datetime.now().date()) - last_date.normalize()).days
        if age_days > STALE_PRICE_SESSIONS + 2:
            out.append(_alert(HALT, "Stale price data",
                              f"Latest close is {last_date.date()} "
                              f"({age_days} days old). Refresh the cache."))

    # --- Missing holdings (only meaningful once trading for real) -------
    if mode in ("PAPER", "LIVE") and holdings.empty:
        out.append(_alert(HALT, "No holdings recorded",
                          "Mode is live/paper but holdings.csv is empty."))

    # --- Held symbol with no price --------------------------------------
    if not holdings.empty:
        close = prices.latest_prices()
        missing = [s for s in holdings["symbol"]
                   if close is None or s not in close.index]
        if missing:
            out.append(_alert(HALT, "Price gap on held name(s)",
                              "No cache price for: " + ", ".join(missing)))

    # --- Rebalance due ---------------------------------------------------
    nxt = state.get("next_rebalance")
    if nxt:
        try:
            nxt_ts = pd.Timestamp(nxt)
            days_to = (nxt_ts.normalize()
                       - pd.Timestamp(datetime.now().date())).days
            if days_to <= REBALANCE_WINDOW_DAYS:
                when = "overdue" if days_to < 0 else f"in {days_to} day(s)"
                out.append(_alert(NOTIFY, "Rebalance due",
                                  f"Next rebalance {nxt_ts.date()} ({when})."))
        except Exception:
            pass

    # --- Validation failure marker in latest audit package --------------
    for pkg in dl.list_audit_packages()[:1]:
        for f in dl.audit_package_files(pkg):
            name = f.name.upper()
            if "FAIL" in name or "HALT" in name:
                out.append(_alert(HALT, "Validation failure flagged",
                                  f"{pkg}: marker file '{f.name}' present."))
                break

    # --- Weight drift beyond ±1.0% of the 10% target --------------------
    if not holdings.empty:
        enriched = metrics.enrich_holdings(
            holdings, prices.latest_prices(), float(state.get("cash", 0.0) or 0.0))
        if "weight" in enriched:
            drifted = enriched[
                (enriched["weight"].notna())
                & ((enriched["weight"] - metrics.TARGET_WEIGHT).abs()
                   > WEIGHT_TOLERANCE)
            ]
            for _, r in drifted.iterrows():
                out.append(_alert(
                    NOTIFY, "Weight drift",
                    f"{r['symbol']} at {r['weight']*100:.1f}% "
                    f"(target {metrics.TARGET_WEIGHT*100:.0f}% ±1.0%)."))

    return out


def counts(alerts: list[dict]) -> tuple[int, int]:
    """(num HALT, num NOTIFY)."""
    halt = sum(1 for a in alerts if a["severity"] == HALT)
    notify = sum(1 for a in alerts if a["severity"] == NOTIFY)
    return halt, notify
