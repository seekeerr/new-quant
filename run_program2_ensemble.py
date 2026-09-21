"""
RESEARCH PROGRAM #2 — ARCHITECTURE COMPARISON: STANDALONE vs ENSEMBLE vs PORTFOLIO.

PRE-REGISTERED (RESEARCH_PROGRAM_2_FINDINGS.md §4). The standalone price-testable search space
is exhausted; per the plan, we now compare production architectures ON EVIDENCE. Three
momentum-family engines each reached the ~17-23% band on survivorship-free data, net of costs:

  A. Champion    — Mom+LowVol, Liquid Top-500, quarterly, Buffer20   (all six gates pass, ~16.5%)
  B. SmallTail   — Mom+LowVol, SmallCap 300-1000, quarterly, Buffer20 (21.8%, Sharpe 1.02; fails
                   only roll-3y-min: cyclical, defensive character)
  C. Breakout    — volume-confirmed breakout, Top-500, MONTHLY, Buffer20 (22.8%, Sharpe 0.66;
                   fails Sharpe/DD/roll-3y-min: offensive, deeper drawdowns)

HYPOTHESIS (pre-registered): B (defensive) and C (offensive) are DIFFERENT mechanisms both at
~22%. If lowly correlated, an offense+defense BLEND may hold ~22% while smoothing the
cyclicality enough to clear ALL SIX gates — the "edge is a pairing, not a factor" lesson that
made Mom+LowVol itself work. This is the decisive test of whether an ensemble beats the best
standalone.

METHOD. Run each sleeve ONCE, net of its own costs. Align on common dates. Form fixed-weight,
daily-rebalanced blends of the net RETURN series (a standard first-pass portfolio screen; it
assumes costless inter-sleeve rebalancing — each sleeve is already net of its OWN trading, so
this understates only the modest cost of shifting capital between sleeves, noted honestly).
Report pairwise correlations (the whole point) and all six gates per blend. Any blend that
clears the five return-series gates then gets the x5/x10 slippage stress by re-running all
sleeves stressed and re-blending with identical weights.

Run:  py run_program2_ensemble.py
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

from run_buffer_experiment import run_buffered_backtest, rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_program2_breakout import make_breakout_scorer
from run_program2_smallcap_validation import (
    stressed_config, subperiod, CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL, SPLIT_DATE,
)

CAP_BASE = 100_000.0
N_STOCKS, BUFFER = 10, 20
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_ensemble"
STRESS_MULTS = [5.0, 10.0]

# Blends to test: name -> {sleeve: weight}
BLENDS = {
    "A champion":          {"A": 1.0},
    "B smalltail":         {"B": 1.0},
    "C breakout":          {"C": 1.0},
    "B+C 50/50":           {"B": 0.5, "C": 0.5},
    "A+C 50/50":           {"A": 0.5, "C": 0.5},
    "A+B 50/50":           {"A": 0.5, "B": 0.5},
    "A+B+C 1/3":           {"A": 1/3, "B": 1/3, "C": 1/3},
}


def run_sleeves(ac, ah, al, av, at, cfg):
    """Return dict sleeve -> net daily return series (each net of its own costs)."""
    def bld(lo, hi):
        return RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, lo, hi)
    mlv = make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)
    sleeves = {}
    print("  [A] champion Mom+LowVol Top-500 quarterly ...")
    a = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq="quarterly",
        buffer=BUFFER, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="A",
        scorer=mlv, universe_builder=bld(0, 500))
    print("  [B] smalltail Mom+LowVol SmallCap 300-1000 quarterly ...")
    b = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq="quarterly",
        buffer=BUFFER, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="B",
        scorer=mlv, universe_builder=bld(300, 1000))
    print("  [C] breakout vol-confirmed Top-500 monthly ...")
    c = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq="monthly",
        buffer=BUFFER, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="C",
        scorer=make_breakout_scorer(av, need_volume=True), universe_builder=bld(0, 500))
    return {"A": a["returns"], "B": b["returns"], "C": c["returns"]}


def blend_returns(sleeves, weights):
    common = None
    for s in weights:
        common = sleeves[s].index if common is None else common.intersection(sleeves[s].index)
    r = sum(w * sleeves[s].reindex(common).fillna(0) for s, w in weights.items())
    return r


def metrics_of(returns, bench_ret, cap=CAP_BASE):
    eq = cap * (1 + returns).cumprod()
    m = compute_metrics(eq, returns, benchmark_returns=bench_ret, initial_capital=cap)
    roll = rolling_3y_cagr(returns)
    h1 = subperiod(eq, returns, bench_ret, eq.index[0], SPLIT_DATE)
    h2 = subperiod(eq, returns, bench_ret, SPLIT_DATE, eq.index[-1])
    return eq, m, roll, h1, h2


def gates(m, roll, h1, h2, stress, bm_cagr):
    g = [("CAGR>17.4%", m.cagr > CHAMP_CAGR), ("Sharpe>=0.69", m.sharpe_ratio >= CHAMP_SHARPE),
         ("MaxDD>=-38.5%", m.max_drawdown >= CHAMP_DD - DD_TOL),
         ("no sign-flip", h1 is not None and h2 is not None and h1.alpha > 0 and h2.alpha > 0),
         ("roll3y min>0", (not roll.empty) and roll.min() > 0)]
    if stress is not None:
        g.append(("survives stress", all(s > bm_cagr for s in stress.values())))
    return g


def main():
    t0 = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    print("=" * 100)
    print("  PROGRAM #2 — ARCHITECTURE COMPARISON: STANDALONE vs ENSEMBLE vs PORTFOLIO".center(100))
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
    print(f"  equity universe: {ac.shape[1]} symbols x {ac.shape[0]} dates\n")

    print("Running the 3 sleeves (net) ...")
    sleeves = run_sleeves(ac, ah, al, av, at, cfg)

    # correlation of daily returns on the common span
    common = sleeves["A"].index.intersection(sleeves["B"].index).intersection(sleeves["C"].index)
    corr = pd.DataFrame({s: sleeves[s].reindex(common).fillna(0) for s in "ABC"}).corr()

    # benchmark aligned to blend span
    bstart, bend = str(common[0].date()), str(common[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    results = {}
    for name, wts in BLENDS.items():
        r = blend_returns(sleeves, wts)
        eq, m, roll, h1, h2 = metrics_of(r, bench_ret)
        results[name] = {"wts": wts, "r": r, "eq": eq, "m": m, "roll": roll, "h1": h1, "h2": h2,
                         "stress": None}

    # stress any blend that clears the 5 return-series gates
    stressed_sleeves = {}
    for name, res in results.items():
        g5 = gates(res["m"], res["roll"], res["h1"], res["h2"], None, bm_cagr)
        if all(p for _, p in g5):
            print(f"\n  [{name}] clears 5 gates -> x5/x10 stress (re-running sleeves stressed) ...")
            stress = {}
            for mult in STRESS_MULTS:
                if mult not in stressed_sleeves:
                    stressed_sleeves[mult] = run_sleeves(ac, ah, al, av, at, stressed_config(cfg, mult))
                sr = blend_returns(stressed_sleeves[mult], res["wts"])
                seq = CAP_BASE * (1 + sr).cumprod()
                stress[mult] = compute_metrics(seq, sr, initial_capital=CAP_BASE).cagr
            res["stress"] = stress

    RDIR.mkdir(parents=True, exist_ok=True)
    _report(results, corr, bm_cagr, bstart, bend)
    _chart(results, bench_eq, corr)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t0:.0f}s)")


def _report(results, corr, bm_cagr, bstart, bend):
    L = []; w = L.append
    w("=" * 100)
    w("  PROGRAM #2 — ARCHITECTURE COMPARISON (STANDALONE vs ENSEMBLE vs PORTFOLIO), NET".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   NIFTY500(px) {bm_cagr:.2%}   Champion bar 17.4%/Sharpe0.69")
    w("Sleeves: A=champion Top-500, B=smalltail 300-1000, C=breakout-monthly. Daily-rebalanced blend.")
    w("")
    w("SLEEVE RETURN CORRELATION (daily, the diversification test):")
    w("        " + "".join(f"{s:>8}" for s in "ABC"))
    for s in "ABC":
        w(f"   {s:<5}" + "".join(f"{corr.loc[s, t]:>8.2f}" for t in "ABC"))
    w("")
    hdr = f"{'Architecture':<16}{'CAGR':>9}{'Sharpe':>8}{'Calmar':>8}{'MaxDD':>9}{'roll3yMin':>11}{'H1 a':>8}{'H2 a':>8}"
    w(hdr); w("-" * 100)
    for name, res in results.items():
        m = res["m"]; rmin = res["roll"].min() if not res["roll"].empty else np.nan
        h1a = res["h1"].alpha if res["h1"] else np.nan
        h2a = res["h2"].alpha if res["h2"] else np.nan
        w(f"{name:<16}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.calmar_ratio:>8.2f}{m.max_drawdown:>9.1%}"
          f"{rmin:>10.1%}{h1a:>+8.1%}{h2a:>+8.1%}")
    w("-" * 100); w("")
    for name, res in results.items():
        g = gates(res["m"], res["roll"], res["h1"], res["h2"], res["stress"], bm_cagr)
        tag = "ALL GATES PASS" if all(p for _, p in g) else "FAILS: " + ", ".join(n for n, p in g if not p)
        line = f"[{name}]  {tag}"
        if res["stress"] is not None:
            line += "  | stress " + " ".join(f"x{int(k)} {v:.1%}" for k, v in res["stress"].items())
        w(line)
    w("-" * 100)
    passers = [n for n, res in results.items()
               if all(p for _, p in gates(res["m"], res["roll"], res["h1"], res["h2"], res["stress"], bm_cagr))]
    ens = [n for n in passers if "+" in n]
    if ens:
        best = max(ens, key=lambda n: results[n]["m"].cagr)
        m = results[best]["m"]
        w(f"VERDICT: ENSEMBLE WINS. '{best}' clears ALL SIX gates at CAGR {m.cagr:.1%}, Sharpe "
          f"{m.sharpe_ratio:.2f}, MaxDD {m.max_drawdown:.1%} — beating the best all-gate standalone")
        w(f"  (champion 17.4%). Offense+defense pairing smoothed the cyclicality. Recommend as the")
        w(f"  production architecture; validate further (OOS, parameter stability) before capital.")
    elif passers:
        w(f"VERDICT: only standalone(s) {passers} clear all gates; no ensemble beat them. "
          f"Best product = champion. Blending did not smooth the cyclicality enough.")
    else:
        best = max(results, key=lambda n: results[n]["m"].sharpe_ratio)
        w(f"VERDICT: NO architecture clears all six gates on the blend span. Best risk-adjusted = "
          f"{best} (Sharpe {results[best]['m'].sharpe_ratio:.2f}). The ~22% engines stay individually")
        w(f"  cyclical; champion remains the only all-gate product. Fundamentals track is the next lever.")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for name, res in results.items():
        m = res["m"]
        rows.append({"architecture": name, "cagr": m.cagr, "sharpe": m.sharpe_ratio,
                     "calmar": m.calmar_ratio, "max_dd": m.max_drawdown, "alpha": m.alpha,
                     "roll3y_min": res["roll"].min() if not res["roll"].empty else np.nan,
                     "h1_alpha": res["h1"].alpha if res["h1"] else np.nan,
                     "h2_alpha": res["h2"].alpha if res["h2"] else np.nan})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)
    corr.to_csv(RDIR / "sleeve_correlation.csv")


def _chart(results, bench_eq, corr):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 11)); gs = GridSpec(2, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Program #2 — Architecture Comparison (standalone vs ensemble, net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.97)
    names = list(results)
    palette = ["#4ecdc4", "#00ff88", "#ff6b6b", "#ffd93d", "#b388ff", "#66d9ef", "#f368e0"]

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for i, n in enumerate(names):
        eq = results[n]["eq"]; ax1.plot(eq.index, eq/eq.iloc[0]*100, color=palette[i % len(palette)],
                                        lw=1.4, label=n)
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3, ncol=2, fontsize=8); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("CAGR vs Sharpe", fontweight="bold")
    x = np.arange(len(names))
    ax2.bar(x, [results[n]["m"].cagr*100 for n in names], color=[palette[i % len(palette)] for i in range(len(names))])
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    a2 = ax2.twinx(); a2.plot(x, [results[n]["m"].sharpe_ratio for n in names], color="#ff6b6b", marker="o", lw=1.4)
    a2.axhline(CHAMP_SHARPE, color="#ff6b6b", ls=":", lw=0.8); a2.set_ylabel("Sharpe", color="#ff6b6b")
    ax2.set_xticks(x); ax2.set_xticklabels(names, fontsize=7, rotation=20); ax2.set_ylabel("CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Sleeve return correlation", fontweight="bold")
    im = ax3.imshow(corr.values, cmap="RdYlGn_r", vmin=-1, vmax=1)
    ax3.set_xticks(range(3)); ax3.set_xticklabels(list("ABC")); ax3.set_yticks(range(3)); ax3.set_yticklabels(list("ABC"))
    for i in range(3):
        for j in range(3):
            ax3.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", color="#000", fontsize=10)
    fig.colorbar(im, ax=ax3, fraction=0.046)

    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
