"""
RESEARCH PROGRAM #2 — TRACK 2, EXPERIMENT 2F: SEASONALITY / CALENDAR (family #5).

PRE-REGISTERED (RESEARCH_PROGRAM_2_TRACK2_DESIGN.md). A genuinely INDEPENDENT family:
calendar/seasonal effects driven by flows, not price trend. The two most robust globally:
  - TURN-OF-MONTH (TOM): returns concentrate in the last trading day + first ~3 of each
    month (salary/SIP inflows, window dressing).
  - HALLOWEEN / SELL-IN-MAY: Nov-Apr strong, May-Oct weak.

HONEST PRE-REGISTERED PRIOR (stated before running): seasonality is a TIMING family — it
moves you to CASH in unfavourable windows. Long-only with NO LEVERAGE, cutting exposure can
only LOWER CAGR vs always-invested; it can raise Sharpe/Calmar by dodging weak periods. So it
is EXPECTED to FAIL gate 1 (CAGR>17.4%). It is tested to (a) DOCUMENT whether the effect
exists in Indian data and (b) measure its risk-timing value for the later portfolio stage —
NOT because it is expected to be a high-CAGR standalone winner.

METHOD (lean, no new engine): run the champion (Mom+LowVol Top-500 quarterly) once, net, to
get its daily return series r_t. Apply each calendar MASK: on in-window days keep r_t; on
out-of-window days earn the daily risk-free rate (cash). Charge a realistic SWITCH COST
(~half a tier-1 round-trip) on every transition day so TOM's ~monthly in/out churn is not
flattered. Also report the RAW seasonal statistic (mean annualised return inside vs outside
each window, for the strategy AND the NIFTY500 benchmark) with the fraction of days invested.

GATES: the same six. A timing overlay that only lifts Sharpe while cutting CAGR is recorded
as a risk-timing NULL for the CAGR objective (like the trend/vol overlays before it).

Run:  py run_program2_seasonality.py
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
from costs.cost_model import CostModel

from run_buffer_experiment import run_buffered_backtest, rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_program2_smallcap_validation import (
    subperiod, CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL, SPLIT_DATE,
)

CAP_BASE = 100_000.0
N_STOCKS = 10
TOP500 = (0, 500)
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_seasonality"
RF_DAILY = (1 + 0.065) ** (1 / 252) - 1


def tom_mask(idx, first_n=3):
    """True on the last trading day of a month and the first `first_n` of the next."""
    s = pd.Series(idx, index=idx)
    ym = idx.to_period("M")
    is_last = pd.Series(ym, index=idx) != pd.Series(ym, index=idx).shift(-1)   # last day of its month
    # first-n of each month
    order = pd.Series(1, index=idx).groupby(ym).cumsum()
    is_firstn = order <= first_n
    return (is_last | is_firstn).values


def halloween_mask(idx):
    """True in Nov-Apr (the strong half)."""
    return np.isin(np.asarray(idx.month), [11, 12, 1, 2, 3, 4])


def apply_calendar(returns, mask, switch_cost):
    """Timed return series: in-window -> strategy return, out -> cash (rf). Charge switch_cost
    (fraction of book) on each transition day (enter or exit)."""
    m = np.asarray(mask, dtype=bool)
    r = returns.values.copy()
    timed = np.where(m, r, RF_DAILY)
    # transitions: where mask changes vs previous day
    trans = np.zeros(len(m), dtype=bool)
    trans[1:] = m[1:] != m[:-1]
    timed = timed - trans * switch_cost
    return pd.Series(timed, index=returns.index)


def _metrics_from_returns(returns, bench_ret, cap):
    eq = cap * (1 + returns).cumprod()
    m = compute_metrics(eq, returns, benchmark_returns=bench_ret, initial_capital=cap)
    roll = rolling_3y_cagr(returns)
    h1 = subperiod(eq, returns, bench_ret, eq.index[0], SPLIT_DATE)
    h2 = subperiod(eq, returns, bench_ret, SPLIT_DATE, eq.index[-1])
    return eq, m, roll, h1, h2


def _gates(m, roll, h1, h2, bm_cagr):
    return [("CAGR>17.4%", m.cagr > CHAMP_CAGR), ("Sharpe>=0.69", m.sharpe_ratio >= CHAMP_SHARPE),
            ("MaxDD>=-38.5%", m.max_drawdown >= CHAMP_DD - DD_TOL),
            ("no sign-flip", h1 is not None and h2 is not None and h1.alpha > 0 and h2.alpha > 0),
            ("roll3y min>0", (not roll.empty) and roll.min() > 0)]


def seasonal_stat(returns, mask, label):
    m = np.asarray(mask, dtype=bool)
    inside = returns.values[m]
    outside = returns.values[~m]
    ann = lambda a: (1 + np.mean(a)) ** 252 - 1 if len(a) else np.nan
    return (f"  {label:<14} inside {ann(inside):>7.1%} ({m.mean():.0%} of days) | "
            f"outside {ann(outside):>7.1%} | spread {ann(inside)-ann(outside):>+7.1%}")


def main():
    t0 = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    print("=" * 100)
    print("  PROGRAM #2 EXP 2F — SEASONALITY / CALENDAR (family #5) — NET".center(100))
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

    builder = RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, TOP500[0], TOP500[1])
    print("\n[base] Mom+LowVol Top-500 quarterly (always-invested underlying) ...")
    base = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq="quarterly",
        buffer=20, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="base",
        scorer=make_mom_lowvol_scorer(0.5, VOL_LOOKBACK), universe_builder=builder)
    r = base["returns"]
    idx = r.index

    # switch cost = half a tier-1 round trip on the whole book
    cm = CostModel(cfg.costs)
    switch_cost = 0.5 * cm.estimate_round_trip_cost_pct(CAP_BASE / N_STOCKS, liquidity_tier=1)

    masks = {"Always-invested": np.ones(len(idx), dtype=bool),
             "Turn-of-month": tom_mask(idx), "Halloween(Nov-Apr)": halloween_mask(idx)}
    variants = {}
    for name, mask in masks.items():
        timed = r if name == "Always-invested" else apply_calendar(r, mask, switch_cost)
        eq, m, roll, h1, h2 = _metrics_from_returns(timed, bench_ret, CAP_BASE)
        variants[name] = {"mask": mask, "eq": eq, "m": m, "roll": roll, "h1": h1, "h2": h2,
                          "invested": float(np.mean(mask))}
        print(f"    {name:<20} CAGR {m.cagr:.2%} | Sharpe {m.sharpe_ratio:.2f} | "
              f"MaxDD {m.max_drawdown:.2%} | invested {np.mean(mask):.0%}")

    eq0 = variants["Always-invested"]["eq"]
    bstart, bend = str(eq0.index[0].date()), str(eq0.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    RDIR.mkdir(parents=True, exist_ok=True)
    _report(variants, r, bench_ret, bm_cagr, bstart, bend, switch_cost)
    _chart(variants, bench_eq)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t0:.0f}s)")


def _report(variants, base_ret, bench_ret, bm_cagr, bstart, bend, switch_cost):
    L = []; w = L.append
    names = list(variants)
    w("=" * 100)
    w("  PROGRAM #2 EXP 2F — SEASONALITY / CALENDAR (family #5, NET)".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   NIFTY500(px) {bm_cagr:.2%}   Champion 17.4%/Sharpe0.69")
    w(f"Underlying: Mom+LowVol Top-500 quarterly. Switch cost {switch_cost:.2%}/transition.")
    w("")
    hdr = f"{'Variant':<22}{'CAGR':>9}{'Sharpe':>8}{'Calmar':>8}{'MaxDD':>9}{'Invested':>10}{'roll3yMin':>11}"
    w(hdr); w("-" * 100)
    for n in names:
        v = variants[n]; m = v["m"]
        rmin = v["roll"].min() if not v["roll"].empty else np.nan
        w(f"{n:<22}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.calmar_ratio:>8.2f}{m.max_drawdown:>9.1%}"
          f"{v['invested']:>9.0%}{rmin:>11.1%}")
    w("-" * 100); w("")
    w("RAW SEASONAL EFFECT (annualised mean return inside vs outside window):")
    for name, mask in [("Turn-of-month", variants["Turn-of-month"]["mask"]),
                       ("Halloween", variants["Halloween(Nov-Apr)"]["mask"])]:
        w(seasonal_stat(base_ret, mask, name + " (strat)"))
        w(seasonal_stat(bench_ret.reindex(base_ret.index).fillna(0), mask, name + " (NIFTY500)"))
    w("")
    for n in names:
        if n == "Always-invested":
            continue
        v = variants[n]
        gates = _gates(v["m"], v["roll"], v["h1"], v["h2"], bm_cagr)
        w(f"[{n}]  {'ALL GATES PASS' if all(p for _, p in gates) else 'FAILS: ' + ', '.join(g for g, p in gates if not p)}")
    w("-" * 100)
    a = variants["Always-invested"]["m"]
    best_tv = max([n for n in names if n != "Always-invested"], key=lambda n: variants[n]["m"].sharpe_ratio)
    bv = variants[best_tv]["m"]
    w(f"VERDICT: calendar timing does NOT beat the champion on CAGR (expected: it cuts exposure).")
    w(f"  Always-invested {a.cagr:.1%}/Sh{a.sharpe_ratio:.2f} vs best-timed {best_tv} "
      f"{bv.cagr:.1%}/Sh{bv.sharpe_ratio:.2f}. Seasonality is a RISK-TIMING family, not a")
    w(f"  high-CAGR standalone edge. Effect existence + risk value recorded for the portfolio stage.")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for n in names:
        v = variants[n]; m = v["m"]
        rows.append({"variant": n, "cagr": m.cagr, "sharpe": m.sharpe_ratio, "calmar": m.calmar_ratio,
                     "max_dd": m.max_drawdown, "invested_frac": v["invested"],
                     "roll3y_min": v["roll"].min() if not v["roll"].empty else np.nan})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _chart(variants, bench_eq):
    plt.style.use("dark_background")
    names = list(variants)
    fig = plt.figure(figsize=(18, 9)); gs = GridSpec(1, 2, figure=fig, wspace=0.22)
    fig.suptitle("Program #2 Exp 2F — Seasonality / Calendar (net)", fontsize=15,
                 fontweight="bold", color="#fff", y=0.98)
    palette = ["#4ecdc4", "#00ff88", "#ffd93d"]
    ax1 = fig.add_subplot(gs[0, 0]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for i, n in enumerate(names):
        eq = variants[n]["eq"]; ax1.plot(eq.index, eq/eq.iloc[0]*100, color=palette[i % 3], lw=1.4, label=n)
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2 = fig.add_subplot(gs[0, 1]); ax2.set_title("CAGR vs Sharpe", fontweight="bold")
    x = np.arange(len(names))
    ax2.bar(x, [variants[n]["m"].cagr*100 for n in names], color=palette[:len(names)])
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    a2 = ax2.twinx(); a2.plot(x, [variants[n]["m"].sharpe_ratio for n in names], color="#ff6b6b", marker="o")
    a2.set_ylabel("Sharpe", color="#ff6b6b")
    ax2.set_xticks(x); ax2.set_xticklabels(names, fontsize=8, rotation=10); ax2.set_ylabel("CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")
    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
