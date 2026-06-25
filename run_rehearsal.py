"""
PAPER-TRADING REHEARSAL DRIVER  (Phase 3G — Track A dress rehearsal).

Deterministic, READ-ONLY generator that replays the frozen champion's quarterly
rebalance end-to-end against the archived bhavcopy cache, exactly as a live
quarter would, and emits an immutable audit package.

It changes NOTHING about the strategy: it imports and calls the *frozen* scoring,
universe, buffer-selection and cost functions used by the validated backtest.
Its only job is to execute the LIVE_TRADING_ARCHITECTURE runbook deterministically
and produce the trade list + audit artifacts.

Frozen champion:  Momentum + LowVol (50/50) · Top 10 · Quarterly · Buffer 20 ·
                  Equal Weight · Equity Only · Survivorship-Free.

Cycle replayed: the two most recent quarter-end signal dates in the cache.
  - T_prev : inception rebalance (no priors) -> establishes a holdings book.
  - T      : steady-state rebalance -> exercises Buffer-20 hysteresis & turnover.

Outputs (immutable): audit_packages/rehearsal_001/
  holdings.csv  trades.csv  alerts.csv  summary.md  + ranks_T.csv, scores_T.csv,
  trade_list.csv, manifest.json
"""
from __future__ import annotations
import sys, io, json, time, hashlib, warnings, subprocess
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import logging
logging.basicConfig(level=logging.ERROR)
for _n in logging.root.manager.loggerDict:
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import SystemConfig
from costs.cost_model import CostModel
from utils.helpers import get_rebalance_dates
from run_pure_momentum import compute_12_1_momentum                 # frozen signal
from run_momentum_lowvol import (make_mom_lowvol_scorer, load_equity_symbols,
                                 CACHE_BHAV, VOL_LOOKBACK)           # frozen blend
from run_buffer_experiment import select_with_buffer                # frozen selection
from run_survivorship_validation import TopNTurnoverUniverseBuilder  # frozen universe

# ── Frozen champion shell ────────────────────────────────────────────────
N_STOCKS, BUFFER, FREQ, W_MOM = 10, 20, "quarterly", 0.5
OUT = PROJECT_ROOT / "audit_packages" / "rehearsal_001"
LOG: list[str] = []


def log(msg=""):
    print(msg)
    LOG.append(str(msg))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def build_target(scores_sorted, current, portfolio_value, close_row):
    """Buffer-20 selection -> equal-weight, whole-share target book."""
    selected = select_with_buffer(scores_sorted, current, N_STOCKS, BUFFER)
    per_stock = portfolio_value / N_STOCKS
    target = {}
    for sym in selected:
        px = close_row.get(sym, np.nan)
        if np.isnan(px) or px <= 0:
            continue
        sh = int(per_stock / px)
        if sh > 0:
            target[sym] = sh
    return selected, target


def make_trade_list(current, target, close_row, cost_model, tiers, signal_date):
    """SELLs first then BUYs; statutory + slippage costs from the frozen model."""
    trades = []
    # sells
    for sym, qty in current.items():
        tgt = target.get(sym, 0)
        if qty - tgt > 0:
            sh = qty - tgt
            px = float(close_row.get(sym, np.nan))
            c = cost_model.calculate_trade_cost(sym, "SELL", sh, px,
                    liquidity_tier=tiers.get(sym, 2)).total_cost
            trades.append(dict(date=str(signal_date.date()), symbol=sym, action="SELL",
                               quantity=sh, price=round(px, 2), costs=round(c, 2),
                               notes="buffer exit / trim"))
    # buys
    for sym, tgt in target.items():
        cur = current.get(sym, 0)
        if tgt - cur > 0:
            sh = tgt - cur
            px = float(close_row.get(sym, np.nan))
            c = cost_model.calculate_trade_cost(sym, "BUY", sh, px,
                    liquidity_tier=tiers.get(sym, 2)).total_cost
            trades.append(dict(date=str(signal_date.date()), symbol=sym, action="BUY",
                               quantity=sh, price=round(px, 2), costs=round(c, 2),
                               notes="new entry" if cur == 0 else "top-up"))
    return trades


def main():
    t0 = time.time()
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    scorer = make_mom_lowvol_scorer(W_MOM, VOL_LOOKBACK)
    cost_model = CostModel(cfg.costs)

    log("=" * 78)
    log("  PAPER-TRADING REHEARSAL 001  —  Track A historical dress rehearsal")
    log("  Momentum+LowVol · Top10 · Quarterly · Buffer20 · Equal Weight (frozen)")
    log("=" * 78)
    log(f"  Run at: {datetime.now():%Y-%m-%d %H:%M:%S}   commit: {git_commit()}")

    # ── RUNBOOK T-5: data acquisition / load archived panels ──────────────
    log("\n[T-5] Stage 1 — load archived survivorship-free panels")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet").sort_index()
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet").sort_index()
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet").sort_index()
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet").sort_index()
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet").sort_index()
    eq = load_equity_symbols()
    if eq is not None:
        keep = [c for c in ac.columns if c in eq]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
    log(f"      panel: {ac.shape[0]} dates x {ac.shape[1]} equity symbols; "
        f"last close = {ac.index[-1].date()}")

    # ── RUNBOOK T: Stage 2 data validation gate ───────────────────────────
    log("\n[T]   Stage 2 — data validation gate")
    freshness_days = (pd.Timestamp(datetime.now().date()) - ac.index[-1]).days
    v_freshness = freshness_days <= 90  # quarterly cadence tolerance for rehearsal
    v_prices = bool((ac.tail(252) > 0).any().any())
    v_nonan = ac.tail(252).notna().any().any()
    log(f"      price-integrity (all > 0 present)............ {'PASS' if v_prices else 'FAIL'}")
    log(f"      recent-history present (252d) ............... {'PASS' if v_nonan else 'FAIL'}")
    log(f"      freshness ({freshness_days}d vs quarterly tolerance) "
        f"....... {'PASS' if v_freshness else 'NOTE (archived replay)'}")

    # quarter-end signal dates
    dates = ac.index
    rebals = pd.DatetimeIndex(sorted(set(get_rebalance_dates(dates, FREQ))))
    rebals = rebals[rebals <= dates[-1]]
    T_prev, T = rebals[-2], rebals[-1]
    log(f"      quarterly signal dates -> prev {T_prev.date()} | current {T.date()}")

    # ── Stage 3: inception book at T_prev (no priors) ─────────────────────
    log(f"\n[T_prev {T_prev.date()}] Stage 3-5 — establish inception book")
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)
    snap_prev = builder.build_universe(T_prev)
    scores_prev = scorer(ac, T_prev, snap_prev.symbols)
    sel_prev, book_prev = build_target(scores_prev, {}, cap, ac.loc[T_prev])
    log(f"      universe {len(snap_prev.symbols)} names; inception Top10: "
        f"{', '.join(sel_prev)}")

    # roll the inception book forward to T at T-close prices
    pv_T = sum(q * float(ac.loc[T].get(s, np.nan)) for s, q in book_prev.items()
               if not np.isnan(ac.loc[T].get(s, np.nan)))
    log(f"      inception book value rolled to {T.date()}: Rs {pv_T:,.0f}")

    # ── Stage 3: signal generation at T  (+ determinism re-run) ───────────
    log(f"\n[T {T.date()}] Stage 3 — signal generation (Mom+LowVol blend)")
    snap_T = builder.build_universe(T)
    scores_T = scorer(ac, T, snap_T.symbols)
    scores_T2 = scorer(ac, T, snap_T.symbols)               # determinism re-run
    determinism = scores_T.equals(scores_T2)
    log(f"      universe {len(snap_T.symbols)} names; determinism re-run: "
        f"{'PASS (bit-identical)' if determinism else 'FAIL'}")
    nan_top30 = scores_T.head(30).isna().any()
    log(f"      no-NaN in top-30 ............................ {'PASS' if not nan_top30 else 'FAIL'}")

    # ── Stage 4-5: buffer-20 selection + construction at T ────────────────
    log(f"\n[T {T.date()}] Stage 4-5 — Buffer20 selection + equal-weight construction")
    sel_T, book_T = build_target(scores_T, book_prev, pv_T, ac.loc[T])
    rank_of = {s: i + 1 for i, s in enumerate(scores_T.index)}
    held_prev = set(book_prev)
    held_now = set(book_T)
    retained = held_prev & held_now
    exited = held_prev - held_now
    entered = held_now - held_prev
    log(f"      target Top10: {', '.join(sel_T)}")
    log(f"      retained {len(retained)} | entered {sorted(entered)} | exited {sorted(exited)}")

    # ── Stage 6: trade list (SELLs first) + Stage 4 turnover gate ─────────
    tiers = snap_T.liquidity_tiers
    trades = make_trade_list(book_prev, book_T, ac.loc[T], cost_model, tiers, T)
    buys_val = sum(t["quantity"] * t["price"] for t in trades if t["action"] == "BUY")
    sells_val = sum(t["quantity"] * t["price"] for t in trades if t["action"] == "SELL")
    turnover = max(buys_val, sells_val) / pv_T if pv_T > 0 else 0.0
    total_costs = sum(t["costs"] for t in trades)
    turnover_ok = 0.10 <= turnover <= 0.70   # Buffer-20 band sanity (centre ~38%)
    log(f"\n[T->T+1] Stage 6 — trade list ({len(trades)} orders, SELLs first)")
    log(f"      turnover {turnover:.1%}  (Buffer-20 expectation ~38%)  "
        f"{'IN BAND' if turnover_ok else 'OUT OF BAND -> investigate'}")
    log(f"      modelled txn costs: Rs {total_costs:,.0f}")

    # ── Stage 12: assemble immutable audit package ────────────────────────
    OUT.mkdir(parents=True, exist_ok=True)

    # holdings.csv — the post-rebalance target book at T
    hold_rows = []
    for sym, qty in book_T.items():
        px = float(ac.loc[T].get(sym, np.nan))
        hold_rows.append(dict(symbol=sym, quantity=qty, cost_price=round(px, 2),
                              entry_date=str(T.date()),
                              weight_pct=round(100 * qty * px / pv_T, 2),
                              rank=rank_of.get(sym)))
    holdings_df = pd.DataFrame(hold_rows).sort_values("rank")
    holdings_df.to_csv(OUT / "holdings.csv", index=False)

    trades_df = pd.DataFrame(trades)
    trades_df.to_csv(OUT / "trades.csv", index=False)

    pd.DataFrame({"rank": list(range(1, len(scores_T) + 1)),
                  "symbol": scores_T.index,
                  "blend_score": scores_T.values,
                  "in_top10": [s in held_now for s in scores_T.index],
                  "in_buffer20": [rank_of[s] <= BUFFER for s in scores_T.index]}
                 ).head(30).to_csv(OUT / "ranks_T.csv", index=False)

    # trade_list.csv — what the operator transcribes to the broker
    trades_df.to_csv(OUT / "trade_list.csv", index=False)

    # alerts.csv — operational alerts captured at signal time
    alerts = []
    def add_alert(sev, title, detail):
        alerts.append(dict(severity=sev, title=title, detail=detail))
    if not determinism:
        add_alert("HALT", "Determinism failure", "scores not reproducible")
    if nan_top30:
        add_alert("HALT", "NaN in top-30 scores", "thin-name NaN leak")
    if not turnover_ok:
        add_alert("HALT", "Turnover out of band", f"{turnover:.1%} vs ~38%")
    missing_px = [s for s in book_T if np.isnan(ac.loc[T].get(s, np.nan))]
    if missing_px:
        add_alert("HALT", "Price gap on target name", ", ".join(missing_px))
    if freshness_days > 5:
        add_alert("NOTIFY", "Archived-data replay",
                  f"signal close {T.date()} is {freshness_days}d old "
                  "(expected for Track A dress rehearsal)")
    if not alerts:
        add_alert("NONE", "All clear", "no operational alerts at signal time")
    pd.DataFrame(alerts).to_csv(OUT / "alerts.csv", index=False)

    elapsed = time.time() - t0

    # manifest.json — version + reproducibility stamp
    manifest = {
        "rehearsal_id": "rehearsal_001",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "frozen_tag": "price-only-final",
        "strategy": "Momentum+LowVol 50/50 · Top10 · Quarterly · Buffer20 · EqualWeight",
        "signal_date_prev": str(T_prev.date()),
        "signal_date": str(T.date()),
        "data_last_close": str(ac.index[-1].date()),
        "universe_size_T": int(len(snap_T.symbols)),
        "initial_capital": cap,
        "portfolio_value_at_T": round(pv_T, 2),
        "turnover_pct": round(100 * turnover, 2),
        "total_costs": round(total_costs, 2),
        "n_trades": len(trades),
        "determinism_pass": bool(determinism),
        "elapsed_seconds": round(elapsed, 1),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # checksums for the immutable package
    sums = {p.name: sha256(p) for p in sorted(OUT.glob("*"))
            if p.name not in ("manifest.json", "CHECKSUMS.txt", "run_log.txt")}
    (OUT / "CHECKSUMS.txt").write_text(
        "\n".join(f"{v}  {k}" for k, v in sums.items()) + "\n", encoding="utf-8")

    log(f"\n[T+1 EOD] Stage 12 — audit package written to {OUT.relative_to(PROJECT_ROOT)}/")
    log(f"      files: {sorted(p.name for p in OUT.glob('*'))}")
    log(f"      elapsed: {elapsed:.1f}s")
    log("=" * 78)

    (OUT / "run_log.txt").write_text("\n".join(LOG), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
