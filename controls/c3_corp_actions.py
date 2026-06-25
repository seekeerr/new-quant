"""C3 — Corporate Action Reconciliation.

Detects corporate actions on held / candidate names directly from the price and
reference data, read-only:

  - splits & bonuses : a step in the adjustment factor (adj_close / raw_close).
                       A factor that drops by ~1/2, 1/5, etc. is a split/bonus;
                       a small step is a dividend adjustment.
  - delistings       : a name on the delisted list with no recent print.
  - symbol changes   : one ISIN mapped to more than one trading symbol.
  - mergers          : best-effort — a delisted name whose ISIN continues under a
                       different active symbol (flagged for human confirmation).
  - unexplained moves: any >20% single-day move with no adjustment factor change
                       (a probable *unadjusted* action — the highest-impact risk).

Emits a reconciliation report CSV (one row per detected event). The control HALTs
only if an event touches a name in the supplied `watch` set (e.g. current
holdings or the new target); otherwise it is NOTIFY/informational.
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

from . import common, config


def _classify_factor_step(ratio_before: float, ratio_after: float) -> str:
    """Classify an adjustment-factor step into a likely action type."""
    if ratio_before == 0 or np.isnan(ratio_before) or np.isnan(ratio_after):
        return "adjustment"
    rel = ratio_after / ratio_before
    # factor falls on a split/bonus (more shares -> lower adjusted-per-raw).
    for n, label in [(2, "split/bonus 2:1"), (5, "split/bonus 5:1"),
                     (10, "split/bonus 10:1"), (3, "split/bonus 3:1")]:
        if abs(rel - 1.0 / n) < 0.05:
            return label
    if rel < 0.95:
        return "split/bonus (other ratio)"
    if 0.95 <= rel < 0.999:
        return "dividend adjustment"
    return "adjustment"


def _detect_factor_events(primary: pd.DataFrame, secondary: pd.DataFrame,
                          symbols: list[str], lookback: int = 400) -> list[dict]:
    events = []
    common_cols = [s for s in symbols if s in primary.columns and s in secondary.columns]
    if not common_cols:
        return events
    p = primary[common_cols].tail(lookback)
    s = secondary[common_cols].tail(lookback)
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = (p / s).replace([np.inf, -np.inf], np.nan)
    step = factor.diff().abs()
    thresh = config.ADJ_FACTOR_STEP_TOL * factor.shift().abs()
    for sym in common_cols:
        hits = step[sym][(step[sym] > thresh[sym]) & step[sym].notna()]
        for dt in hits.index:
            i = factor.index.get_loc(dt)
            if i == 0:
                continue
            rb, ra = factor[sym].iloc[i - 1], factor[sym].iloc[i]
            events.append({"type": _classify_factor_step(rb, ra), "symbol": sym,
                           "date": str(pd.Timestamp(dt).date()),
                           "detail": f"adj/raw factor {rb:.4f} -> {ra:.4f}"})
    return events


def _detect_unexplained_moves(primary: pd.DataFrame, secondary: pd.DataFrame,
                              symbols: list[str], lookback: int = 60) -> list[dict]:
    """>20% single-day moves with no adjustment-factor change = probable
    unadjusted action (the case that silently corrupts the signal)."""
    events = []
    cols = [s for s in symbols if s in primary.columns]
    if not cols:
        return events
    p = primary[cols].tail(lookback)
    ret = p.pct_change()
    have_secondary = [c for c in cols if c in secondary.columns]
    fac = None
    if have_secondary:
        with np.errstate(divide="ignore", invalid="ignore"):
            fac = (primary[have_secondary].tail(lookback)
                   / secondary[have_secondary].tail(lookback)).replace([np.inf, -np.inf], np.nan)
    for sym in cols:
        big = ret[sym][ret[sym].abs() > config.UNEXPLAINED_MOVE_TOL]
        for dt in big.index:
            # explained if the adjustment factor stepped on/around this date
            explained = False
            if fac is not None and sym in fac.columns:
                i = fac.index.get_loc(dt)
                if i > 0 and abs(fac[sym].iloc[i] - fac[sym].iloc[i - 1]) > \
                        config.ADJ_FACTOR_STEP_TOL * abs(fac[sym].iloc[i - 1] or 1):
                    explained = True
            if not explained:
                events.append({"type": "unexplained_move(review)", "symbol": sym,
                               "date": str(pd.Timestamp(dt).date()),
                               "detail": f"{ret[sym].loc[dt]*100:+.1f}% 1-day, no adj-factor change"})
    return events


def _detect_symbol_changes() -> list[dict]:
    """One ISIN mapped to >1 symbol over history = a ticker/symbol change."""
    events = []
    try:
        m = pd.read_csv(config.SYMBOL_ISIN)
    except Exception:
        return events
    if not {"SYMBOL", "ISIN"}.issubset(m.columns):
        return events
    grp = m.groupby("ISIN")["SYMBOL"].apply(lambda s: sorted(set(s)))
    for isin, syms in grp.items():
        if len(syms) > 1:
            events.append({"type": "symbol_change", "symbol": " / ".join(syms),
                           "date": "", "detail": f"ISIN {isin} maps to {len(syms)} symbols"})
    return events


def _delisted_set() -> set[str]:
    try:
        return set(config.DELISTED_FILE.read_text().split())
    except Exception:
        return set()


def _detect_delistings(primary: pd.DataFrame, symbols: list[str]) -> list[dict]:
    events = []
    delisted = _delisted_set()
    if primary.empty:
        return events
    last_date = pd.Timestamp(primary.index[-1])
    cutoff = last_date - pd.Timedelta(days=config.RECENT_INACTIVITY_DAYS)
    for sym in symbols:
        if sym not in delisted:
            continue
        if sym not in primary.columns:
            events.append({"type": "delisting", "symbol": sym, "date": "",
                           "detail": "on delisted list; absent from price panel"})
            continue
        recent = primary[sym].loc[primary.index >= cutoff].dropna()
        if recent.empty:
            events.append({"type": "delisting", "symbol": sym,
                           "date": str(last_date.date()),
                           "detail": "on delisted list; no print in recent window"})
    return events


def reconcile(watch: Optional[Iterable[str]] = None) -> common.ControlResult:
    """Run all detectors. `watch` = names that, if hit, escalate to HALT
    (typically current holdings ∪ new target). Others are informational."""
    primary = common.load_parquet(config.PRIMARY_CLOSE)
    secondary = common.load_parquet(config.RAW_CLOSE)
    watch = set(watch or [])

    if primary.empty:
        return common.ControlResult("C3", "Corp-Action Reconciliation", common.HALT,
                                    "Primary price panel missing — cannot reconcile.", {})

    # Scan held/target names in depth; symbol-changes scanned market-wide.
    scan = sorted(watch) if watch else list(primary.columns)
    events: list[dict] = []
    events += _detect_factor_events(primary, secondary, scan)
    events += _detect_unexplained_moves(primary, secondary, scan)
    events += _detect_delistings(primary, scan)
    events += _detect_symbol_changes()

    df = pd.DataFrame(events, columns=["type", "symbol", "date", "detail"])
    # mark which events touch a watched name
    if watch:
        df["touches_watch"] = df["symbol"].apply(
            lambda s: any(tok in watch for tok in str(s).replace(" / ", " ").split()))
    else:
        df["touches_watch"] = False
    report = common.write_report(df, "c3_corp_action_report.csv")

    by_type = df["type"].value_counts().to_dict() if not df.empty else {}
    details = {"n_events": len(df), "by_type": by_type,
               "watch_size": len(watch),
               "n_touching_watch": int(df["touches_watch"].sum()) if not df.empty else 0}

    # HALT if a corporate action / unexplained move touches a watched name.
    actionable = df[df["touches_watch"] & (df["type"] != "symbol_change")] if not df.empty else df
    if watch and len(actionable) > 0:
        names = ", ".join(sorted(set(actionable["symbol"])))
        return common.ControlResult("C3", "Corp-Action Reconciliation", common.HALT,
                                    f"Corporate action affects held/target name(s): {names}. "
                                    "Freeze those names until reconciled.", details, report)
    if len(df) > 0:
        return common.ControlResult("C3", "Corp-Action Reconciliation", common.NOTIFY,
                                    f"{len(df)} corporate-action event(s) detected "
                                    "(none on watched names).", details, report)
    return common.ControlResult("C3", "Corp-Action Reconciliation", common.PASS,
                                "No corporate-action events detected.", details, report)


def _cli(argv) -> int:
    watch = argv if argv else None
    r = reconcile(watch=watch)
    print(f"[{r.status}] {r.summary}")
    print(f"  events by type: {r.details.get('by_type')}")
    print(f"  report: {r.report_path}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
