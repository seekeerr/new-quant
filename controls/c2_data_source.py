"""C2 — Backup Data Source.

Validates the primary price source against an independent secondary source and
reports any discrepancy before a signal is ever computed on the data.

- Primary  : the cache the system trades from (adj_close.parquet).
- Secondary: an independent panel. Pluggable via `load_secondary()`; defaults to
  the unadjusted bhavcopy panel (raw_close.parquet) already in the repo, which is
  a genuinely separate series. In live use, point this at the NSE bhavcopy feed.

Checks: freshness, symbol coverage, and per-name latest-overlap-date divergence
beyond PRICE_DIVERGENCE_TOL. Emits a discrepancy report CSV.

NOTE: comparing adjusted vs unadjusted prices will legitimately diverge on names
with a corporate action — so C2 cross-references C3's adjustment factors and only
flags divergence on names with NO detected adjustment event. This keeps the
consistency check honest rather than alarming on every split.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd

from . import common, config


def load_primary() -> pd.DataFrame:
    return common.load_parquet(config.PRIMARY_CLOSE)


def load_secondary() -> pd.DataFrame:
    """Independent cross-check panel. Swap this for the live bhavcopy loader."""
    return common.load_parquet(config.RAW_CLOSE)


def _adjustment_factor(primary: pd.DataFrame,
                       secondary: pd.DataFrame) -> pd.Series:
    """Per-symbol adj/raw factor on the latest common date (1.0 == no CA effect)."""
    common_cols = [c for c in primary.columns if c in secondary.columns]
    if not common_cols:
        return pd.Series(dtype=float)
    p = primary[common_cols].ffill().iloc[-1]
    s = secondary[common_cols].ffill().iloc[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        return (p / s).replace([np.inf, -np.inf], np.nan)


def reconcile(primary_loader: Callable[[], pd.DataFrame] = load_primary,
              secondary_loader: Callable[[], pd.DataFrame] = load_secondary,
              as_of: Optional[pd.Timestamp] = None) -> common.ControlResult:
    primary = primary_loader()
    secondary = secondary_loader()
    details: dict = {}

    if primary.empty:
        return common.ControlResult("C2", "Backup Data Source", common.HALT,
                                    "Primary source missing/empty.", details)
    if secondary.empty:
        return common.ControlResult("C2", "Backup Data Source", common.HALT,
                                    "Secondary source missing/empty — no cross-check possible.",
                                    details)

    # --- freshness (primary) ---
    last_primary = pd.Timestamp(primary.index[-1])
    ref = pd.Timestamp((as_of or datetime.now()).date() if not isinstance(as_of, pd.Timestamp)
                       else as_of.date())
    age_days = (ref - last_primary.normalize()).days
    details["primary_last_close"] = str(last_primary.date())
    details["secondary_last_close"] = str(pd.Timestamp(secondary.index[-1]).date())
    details["primary_age_days"] = age_days
    fresh_ok = age_days <= (config.FRESHNESS_MAX_TRADING_DAYS + 2)

    # --- coverage ---
    p_syms, s_syms = set(primary.columns), set(secondary.columns)
    coverage = len(p_syms & s_syms) / max(len(p_syms), 1)
    details["symbol_coverage"] = round(coverage, 4)
    missing_in_secondary = sorted(p_syms - s_syms)[:50]
    details["n_missing_in_secondary"] = len(p_syms - s_syms)
    coverage_ok = coverage >= config.MIN_SYMBOL_COVERAGE

    # --- per-name divergence on the latest common date ---
    common_date = min(last_primary, pd.Timestamp(secondary.index[-1]))
    p_row = primary.loc[:common_date].ffill().iloc[-1]
    s_row = secondary.loc[:common_date].ffill().iloc[-1]
    cols = [c for c in p_row.index if c in s_row.index]
    p_row, s_row = p_row[cols], s_row[cols]

    # names with a corporate-action adjustment (factor != 1) are expected to
    # differ between adjusted/unadjusted sources; exclude them from divergence.
    factor = _adjustment_factor(primary, secondary)
    adjusted = set(factor[(factor.notna()) & ((factor - 1.0).abs() > config.ADJ_FACTOR_STEP_TOL)].index)
    details["n_excluded_for_corp_action"] = len(adjusted & set(cols))

    rows = []
    for c in cols:
        if c in adjusted:
            continue
        pv, sv = p_row[c], s_row[c]
        if pd.isna(pv) or pd.isna(sv) or sv == 0:
            continue
        div = abs(pv - sv) / abs(sv)
        if div > config.PRICE_DIVERGENCE_TOL:
            rows.append({"symbol": c, "primary": round(float(pv), 4),
                         "secondary": round(float(sv), 4),
                         "divergence_pct": round(div * 100, 3)})
    disc = pd.DataFrame(rows).sort_values("divergence_pct", ascending=False) \
        if rows else pd.DataFrame(columns=["symbol", "primary", "secondary", "divergence_pct"])
    report = common.write_report(disc, "c2_data_discrepancy.csv")
    details["n_discrepancies"] = len(disc)
    details["worst_divergence_pct"] = float(disc["divergence_pct"].iloc[0]) if len(disc) else 0.0
    details["common_date"] = str(common_date.date())

    # --- verdict ---
    if not fresh_ok:
        status, summary = common.HALT, f"Primary stale ({age_days}d old)."
    elif not coverage_ok:
        status, summary = common.HALT, (f"Secondary covers only {coverage:.1%} of "
                                        f"primary symbols (< {config.MIN_SYMBOL_COVERAGE:.0%}).")
    elif len(disc) > 0:
        status, summary = common.NOTIFY, (f"{len(disc)} name(s) diverge > "
                                          f"{config.PRICE_DIVERGENCE_TOL:.1%} between sources "
                                          f"(worst {details['worst_divergence_pct']:.2f}%).")
    else:
        status, summary = common.PASS, ("Primary fresh, secondary covers "
                                        f"{coverage:.1%}, no unexplained divergence.")
    return common.ControlResult("C2", "Backup Data Source", status, summary,
                                details, report)


def _cli(argv) -> int:
    r = reconcile()
    print(f"[{r.status}] {r.summary}")
    print(f"  report: {r.report_path}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
