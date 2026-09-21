"""
RESEARCH PROGRAM #2 — TRACK 2, EXPERIMENT 2D: VOLATILITY-EXPANSION / SQUEEZE BREAKOUT.

PRE-REGISTERED (RESEARCH_PROGRAM_2_TRACK2_DESIGN.md). The last price-testable independent
family: a volatility CONTRACTION (a low-vol "coil") that resolves into an EXPANSION with a
directional up-move tends to precede a sustained run. This is distinct from plain breakout
(2B, new-high) — the trigger is a volatility REGIME shift, not price level — though it is a
momentum-family cousin, so the pre-registered prior is that it behaves like 2B (real gross
trend edge, likely fails the strict risk gates).

EVENT (reuses the 2E event-execution engine via injected signals — no new engine):
  squeezed  = 20d realised vol <= 0.7 * 100d realised vol      (the coil / contraction)
  breakout  = close >= its trailing 20-day high                 (upside expansion)
  event     = squeezed AND breakout      (a break out of a low-vol coil, to the upside)
  strength  = 100d-vol / 20d-vol          (tighter coil ranks first when events compete)
  detected at close t, ENTER at close t+1, hold 40d, max 10 EW slots, NET of costs.
Single pre-registered config (no grid — a fresh anomaly must not be tuned to pass).

UNIVERSES: Liquid Top-500 and All-Equity-filtered. GATES: the same six; x5/x10 stress +
impact capacity run only on cells that clear the headline gates.

Run:  py run_program2_vol_expansion.py
"""
import sys, io, time, warnings
from pathlib import Path

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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics

from run_buffer_experiment import rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import load_equity_symbols
from run_program2_event_drift import run_event_drift_backtest, HOLD_DAYS, MAX_POS
from run_program2_smallcap_validation import (
    stressed_config, subperiod, CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL,
    SPLIT_DATE, CAP_LADDER, STRESS_MULTS,
)

CAP_BASE = 100_000.0
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_vol_expansion"
VOL_SHORT, VOL_LONG, SQUEEZE_K, BREAK_LB = 20, 100, 0.7, 20
CELLS = [("Top-500", 0, 500), ("All-filtered", 0, 10**9)]


def build_signals(close):
    """squeezed (20d vol <= 0.7*100d vol) AND upside breakout (new 20d high)."""
    ret = close.pct_change()
    v_s = ret.rolling(VOL_SHORT).std()
    v_l = ret.rolling(VOL_LONG).std()
    squeezed = v_s <= SQUEEZE_K * v_l
    breakout = close >= close.rolling(BREAK_LB).max()
    is_event = squeezed & breakout
    strength = (v_l / v_s.replace(0, np.nan))            # tighter coil ranks first
    return is_event.fillna(False), strength


def _metrics(res, bench_ret, cap):
    m = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                        trades=res["trades"], total_costs=res["total_costs"], initial_capital=cap)
    roll = rolling_3y_cagr(res["returns"])
    h1 = subperiod(res["equity_curve"], res["returns"], bench_ret, res["equity_curve"].index[0], SPLIT_DATE)
    h2 = subperiod(res["equity_curve"], res["returns"], bench_ret, SPLIT_DATE, res["equity_curve"].index[-1])
    return m, roll, h1, h2


def _gates(m, roll, h1, h2, stress, bm_cagr):
    g = [("CAGR>17.4%", m.cagr > CHAMP_CAGR), ("Sharpe>=0.69", m.sharpe_ratio >= CHAMP_SHARPE),
         ("MaxDD>=-38.5%", m.max_drawdown >= CHAMP_DD - DD_TOL),
         ("no sign-flip", h1 is not None and h2 is not None and h1.alpha > 0 and h2.alpha > 0),
         ("roll3y min>0", (not roll.empty) and roll.min() > 0)]
    if stress is not None:
        g.append(("survives stress", all(s.cagr > bm_cagr for s in stress.values())))
    return g


def main():
    t0 = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    print("=" * 100)
    print("  PROGRAM #2 EXP 2D — VOLATILITY-EXPANSION / SQUEEZE BREAKOUT — NET".center(100))
    print("=" * 100)

    bench_ret = get_benchmark_returns(start, end)
    print("\nLoading survivorship-free bhavcopy panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
    print(f"  equity universe: {ac.shape[1]} symbols x {ac.shape[0]} dates")

    print("\nBuilding squeeze-breakout signals ...")
    is_event, strength = build_signals(ac)
    print(f"  event days: {int(is_event.values.sum()):,} symbol-days flagged")

    def builder(lo, hi):
        return RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, lo, hi)

    cells = {}
    for label, lo, hi in CELLS:
        print(f"\n[{label}] vol-expansion net ...")
        res = run_event_drift_backtest(ac, av, at, universe_builder=builder(lo, hi), config=cfg,
            initial_capital=CAP_BASE, apply_costs=True, label=label,
            event_signal=is_event, strength_signal=strength)
        if res["equity_curve"].empty:
            print(f"    (no equity curve for {label})"); continue
        m, roll, h1, h2 = _metrics(res, bench_ret, CAP_BASE)
        cells[label] = {"lo": lo, "hi": hi, "res": res, "m": m, "roll": roll, "h1": h1, "h2": h2}
        print(f"    CAGR {m.cagr:.2%} | Sharpe {m.sharpe_ratio:.2f} | MaxDD {m.max_drawdown:.2%} | "
              f"trades {res['total_trades']} | costs Rs {res['total_costs']:,.0f}")

    if not cells:
        print("No cells produced results."); return
    eq0 = cells[list(cells)[0]]["res"]["equity_curve"]
    bstart, bend = str(eq0.index[0].date()), str(eq0.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    for label, c in cells.items():
        m = c["m"]
        headline_ok = (m.cagr > CHAMP_CAGR and m.sharpe_ratio >= CHAMP_SHARPE
                       and m.max_drawdown >= CHAMP_DD - DD_TOL)
        c["headline_ok"] = headline_ok; c["stress"] = None; c["capacity"] = None
        if headline_ok:
            print(f"\n  [{label}] clears headline gates -> x5/x10 stress + impact capacity ...")
            stress = {}
            for mult in STRESS_MULTS:
                sr = run_event_drift_backtest(ac, av, at, universe_builder=builder(c["lo"], c["hi"]),
                    config=stressed_config(cfg, mult), initial_capital=CAP_BASE, apply_costs=True,
                    label=f"{label} x{mult:.0f}", event_signal=is_event, strength_signal=strength)
                stress[mult] = compute_metrics(sr["equity_curve"], sr["returns"], benchmark_returns=bench_ret,
                    trades=sr["trades"], total_costs=sr["total_costs"], initial_capital=CAP_BASE)
            c["stress"] = stress
            cap_rows = []
            for capital in CAP_LADDER:
                res = run_event_drift_backtest(ac, av, at, universe_builder=builder(c["lo"], c["hi"]),
                    config=cfg, initial_capital=capital, apply_costs=True, impact=True,
                    label=f"{label} Rs{capital/1e5:.0f}L", event_signal=is_event, strength_signal=strength)
                cm = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                    trades=res["trades"], total_costs=res["total_costs"], initial_capital=capital)
                cap_rows.append({"capital": capital, "cagr": cm.cagr, "sharpe": cm.sharpe_ratio,
                                 "impact": res.get("total_impact", 0.0)})
            c["capacity"] = cap_rows

    RDIR.mkdir(parents=True, exist_ok=True)
    _report(cells, bm_cagr, bstart, bend, bench_eq)
    _chart(cells, bench_eq, bm_cagr)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t0:.0f}s)")


def _report(cells, bm_cagr, bstart, bend, bench_eq):
    L = []; w = L.append
    labels = list(cells)
    w("=" * 100)
    w("  PROGRAM #2 EXP 2D — VOLATILITY-EXPANSION / SQUEEZE BREAKOUT (NET)".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   NIFTY500(px) {bm_cagr:.2%}   Champion 17.4%/Sharpe0.69")
    w(f"Event: 20d-vol <= {SQUEEZE_K}*100d-vol AND close>={BREAK_LB}d-high; enter t+1; "
      f"hold {HOLD_DAYS}d; max {MAX_POS} EW slots.")
    w("")
    hdr = (f"{'Universe':<15}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'Alpha':>9}{'Trades':>8}"
           f"{'roll3yMin':>11}{'H1 a':>8}{'H2 a':>8}")
    w(hdr); w("-" * 100)
    for label in labels:
        c = cells[label]; m = c["m"]
        rmin = c["roll"].min() if not c["roll"].empty else np.nan
        h1a = c["h1"].alpha if c["h1"] else np.nan
        h2a = c["h2"].alpha if c["h2"] else np.nan
        w(f"{label:<15}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}{m.alpha:>+9.1%}"
          f"{c['res']['total_trades']:>8d}{rmin:>10.1%}{h1a:>+8.1%}{h2a:>+8.1%}")
    w("-" * 100); w("")
    for label in labels:
        c = cells[label]; m = c["m"]
        gates = _gates(m, c["roll"], c["h1"], c["h2"], c["stress"], bm_cagr)
        w(f"[{label}]  {'ALL GATES PASS' if all(p for _, p in gates) else 'FAILS: ' + ', '.join(n for n, p in gates if not p)}")
        if c["stress"] is not None:
            w("    stress: " + " ".join(f"x{int(k)} {v.cagr:.1%}" for k, v in c["stress"].items())
              + f"  (bm {bm_cagr:.1%})")
        if c["capacity"] is not None:
            w("    capacity: " + " ".join(f"Rs{r['capital']/1e5:.0f}L {r['cagr']:.1%}" for r in c["capacity"]))
    w("")
    any_pass = any(all(p for _, p in _gates(cells[l]["m"], cells[l]["roll"], cells[l]["h1"],
                       cells[l]["h2"], cells[l]["stress"], bm_cagr)) for l in labels)
    w("-" * 100)
    if any_pass:
        w("VERDICT: volatility-expansion CLEARS all gates -> promote for deeper validation.")
    else:
        best = max(labels, key=lambda l: cells[l]["m"].sharpe_ratio)
        bm = cells[best]["m"]
        w(f"VERDICT: NO vol-expansion cell clears all gates. Best = {best} "
          f"(CAGR {bm.cagr:.1%}, Sharpe {bm.sharpe_ratio:.2f}, alpha {bm.alpha:+.1%}).")
        w("  Squeeze-breakout does not beat the champion net of costs as a standalone.")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")
    rows = []
    for label in labels:
        c = cells[label]; m = c["m"]
        rows.append({"universe": label, "cagr": m.cagr, "sharpe": m.sharpe_ratio, "max_dd": m.max_drawdown,
                     "alpha": m.alpha, "trades": c["res"]["total_trades"],
                     "roll3y_min": c["roll"].min() if not c["roll"].empty else np.nan,
                     "h1_alpha": c["h1"].alpha if c["h1"] else np.nan,
                     "h2_alpha": c["h2"].alpha if c["h2"] else np.nan, "headline_ok": c["headline_ok"]})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _chart(cells, bench_eq, bm_cagr):
    plt.style.use("dark_background")
    labels = list(cells)
    fig = plt.figure(figsize=(18, 9)); gs = GridSpec(1, 2, figure=fig, wspace=0.22)
    fig.suptitle("Program #2 Exp 2D — Volatility-Expansion / Squeeze Breakout (net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.98)
    palette = ["#00ff88", "#ffd93d", "#ff6b6b"]
    ax1 = fig.add_subplot(gs[0, 0]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for i, label in enumerate(labels):
        eq = cells[label]["res"]["equity_curve"]
        ax1.plot(eq.index, eq/eq.iloc[0]*100, color=palette[i % 3], lw=1.4, label=label)
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2 = fig.add_subplot(gs[0, 1]); ax2.set_title("CAGR & Sharpe vs champion", fontweight="bold")
    x = np.arange(len(labels))
    ax2.bar(x, [cells[l]["m"].cagr*100 for l in labels], color=palette[:len(labels)])
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    ax2.axhline(bm_cagr*100, color="#888", ls="--", lw=1, label=f"bm {bm_cagr:.0%}")
    a2 = ax2.twinx(); a2.plot(x, [cells[l]["m"].sharpe_ratio for l in labels], color="#ff6b6b", marker="o")
    a2.set_ylabel("Sharpe", color="#ff6b6b")
    ax2.set_xticks(x); ax2.set_xticklabels(labels); ax2.set_ylabel("CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")
    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
